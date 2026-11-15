"""
Ask ServeSync: one search box to *ask a question* or *jump anywhere* (Ctrl+K).

    [ (search) Ask a question or type a page name...            ]
      Ask: "who is free saturday"                        Enter
      Go to Calendar                                     Ctrl+4
    ----------------------------------------------------------------
    Who is free Saturday morning?                      (question)
    15 active volunteers are usually free on Saturday
    mornings: ...                                       (answer)
    [ Open Calendar ]   I read this as: who is free on Saturday mornings
    ----------------------------------------------------------------
    Try asking
      Which shifts need volunteers this week?
      How do I ...?

It is styled like a search panel, not a chat: each question and its answer
form one plain row, newest last, separated by hairlines. A chat look would
suggest a person or a general chatbot is replying; this is a lookup over the
organization's own records, and the layout says so.

Keyboard model: focus stays in the text box. Up/Down move through the list,
Enter runs the highlighted row (asking is always the first row), Esc
closes. Every answer is announced to screen readers, and the transcript
can be read with Tab.

Privacy note shown in the dialog: answers come only from this computer's
records. Nothing is sent over the internet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from servesync.core.i18n import tr
from servesync.services.assistant import Answer, rank_commands
from servesync.ui import assets
from servesync.ui.context import AppContext
from servesync.ui.motion import fade_in
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import clear_layout, guarded, make_button, make_label

ASK_ROW = "__ask__"


@dataclass(frozen=True, slots=True)
class Command:
    """Something the box can do besides answering: open a page, run an action."""

    label: str
    run: Callable[[], None]
    shortcut: str = ""


class AssistantDialog(QDialog):
    def __init__(self, ctx: AppContext, commands: list[Command], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.commands = {command.label: command for command in commands}
        self.setWindowTitle(tr("Ask ServeSync"))
        self.setAccessibleName(tr("Ask ServeSync"))
        self.resize(760, 640)

        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 16)
        column.setSpacing(16)
        title_row = QHBoxLayout()
        title_row.addWidget(make_label(tr("Ask ServeSync"), "section"))
        title_row.addStretch(1)
        title_row.addWidget(make_label(tr("Esc to close"), "kbd"))
        column.addLayout(title_row)

        self.input = QLineEdit()
        self.input.setObjectName("AskInput")
        self.input.setPlaceholderText(tr("Ask a question, or type a page name to go there"))
        self.input.setAccessibleName(tr("Ask a question or type a page name"))
        self.input.setAccessibleDescription(
            tr("Press Enter to ask. Use the up and down arrows to choose a page instead.")
        )
        self.input.setClearButtonEnabled(True)
        self.input.textChanged.connect(self._update_matches)
        self.input.returnPressed.connect(self._run_current)
        self.input.installEventFilter(self)
        column.addWidget(self.input)

        self.matches = QListWidget()
        self.matches.setAccessibleName(tr("Suggestions"))
        self.matches.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the text box keeps focus; arrows move the highlight
        self.matches.itemClicked.connect(lambda item: self._run(item))
        self.matches.setMaximumHeight(200)
        self.matches.hide()
        column.addWidget(self.matches)

        self.transcript_area = QScrollArea()
        self.transcript_area.setWidgetResizable(True)
        self.transcript_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.transcript = QVBoxLayout(holder)
        self.transcript.setContentsMargins(0, 0, 8, 0)
        self.transcript.setSpacing(0)
        self.transcript.addStretch(1)
        self.transcript_area.setWidget(holder)
        column.addWidget(self.transcript_area, 1)

        self.suggestion_row = QVBoxLayout()
        self.suggestion_row.setSpacing(0)
        column.addLayout(self.suggestion_row)
        self._show_suggestions(ctx.services.assistant.suggestions(ctx.session), tr("Try asking"))
        column.addWidget(
            make_label(
                tr("Answers come only from the records on this computer. Nothing is sent over the internet."),
                "hint",
                wrap=True,
            )
        )
        self.answers: list[Answer] = []
        self.input.setFocus()

    # ------------------------------------------------------------ typing

    def _update_matches(self, text: str) -> None:
        self.matches.clear()
        query = text.strip()
        if not query:
            self.matches.hide()
            return
        ask = QListWidgetItem(tr("Ask: “{query}”", query=query))
        ask.setData(Qt.ItemDataRole.UserRole, ASK_ROW)
        ask.setIcon(assets.icon("corner-down-left", current_palette().text_muted, 16))
        self.matches.addItem(ask)
        for _score, label in rank_commands(query, self.commands, limit=5):
            command = self.commands[label]
            item = QListWidgetItem(label + (f"    {command.shortcut}" if command.shortcut else ""))
            item.setData(Qt.ItemDataRole.UserRole, label)
            self.matches.addItem(item)
        self.matches.setCurrentRow(0)
        self.matches.setVisible(self.matches.count() > 1)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if watched is self.input and event.type() == QEvent.Type.KeyPress and not self.matches.isHidden():
            assert isinstance(event, QKeyEvent)
            step = {Qt.Key.Key_Down: 1, Qt.Key.Key_Up: -1}.get(Qt.Key(event.key()))
            if step is not None:
                row = (self.matches.currentRow() + step) % self.matches.count()
                self.matches.setCurrentRow(row)
                current = self.matches.currentItem()
                if current is not None:
                    self.ctx.announce(current.text())
                return True
        return super().eventFilter(watched, event)

    def _run_current(self) -> None:
        item = self.matches.currentItem() if not self.matches.isHidden() else None
        if item is None or item.data(Qt.ItemDataRole.UserRole) == ASK_ROW:
            self.ask(self.input.text())
        else:
            self._run(item)

    def _run(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.ItemDataRole.UserRole)
        if key == ASK_ROW:
            self.ask(self.input.text())
            return
        command = self.commands.get(str(key))
        if command is not None:
            self.accept()
            QTimer.singleShot(0, command.run)  # after this window closes

    # ------------------------------------------------------------ asking

    @guarded
    def ask(self, question: str) -> Answer | None:
        text = question.strip()
        if not text:
            return None
        answer = self.ctx.services.assistant.ask(self.ctx.session, text)
        self.answers.append(answer)
        self._add_answer(text, answer)
        self.input.clear()
        self.matches.hide()
        self._show_suggestions(answer.follow_ups, tr("Follow up"))
        self.ctx.announce(answer.text.replace("•", ""))
        QTimer.singleShot(0, self._scroll_to_end)
        return answer

    def _add_answer(self, question: str, answer: Answer) -> QFrame:
        """One result row: the question, the answer, its page buttons, and how it was understood."""
        row = QFrame()
        row.setProperty("answer", True)
        body = QVBoxLayout(row)
        body.setContentsMargins(0, 16, 0, 16)
        body.setSpacing(8)
        asked = make_label(question, "name", wrap=True, selectable=True)
        asked.setAccessibleName(tr("You said: {text}", text=question))
        body.addWidget(asked)
        reply = make_label(answer.text, None, wrap=True, selectable=True)
        reply.setFocusPolicy(Qt.FocusPolicy.TabFocus)  # Tab reaches each answer for screen readers
        reply.setAccessibleName(tr("ServeSync said: {text}", text=answer.text))
        body.addWidget(reply)
        if answer.actions or answer.understood:
            footer = QHBoxLayout()
            footer.setSpacing(16)
            for action in answer.actions:
                footer.addWidget(
                    make_button(
                        action.label,
                        kind="secondary",
                        on_click=partial(self._open, action.page, dict(action.options)),
                    )
                )
            if answer.understood:
                footer.addWidget(
                    make_label(tr("I read this as: {understood}", understood=answer.understood), "hint", wrap=True),
                    1,
                )
            else:
                footer.addStretch(1)
            body.addLayout(footer)
        self.transcript.insertWidget(self.transcript.count() - 1, row)
        fade_in(row)
        return row

    def _open(self, page: str, options: dict[str, object]) -> None:
        self.accept()
        self.ctx.go(page, **options)

    def _show_suggestions(self, questions: tuple[str, ...], heading: str) -> None:
        clear_layout(self.suggestion_row)
        if not questions:
            return
        self.suggestion_row.addWidget(make_label(heading, "hint"))
        # Plain rows of text, like a search page's "related searches", rather than chips.
        for question in questions[:4]:
            self.suggestion_row.addWidget(make_button(question, kind="chip", on_click=partial(self.ask, question)))

    def _scroll_to_end(self) -> None:
        bar = self.transcript_area.verticalScrollBar()
        bar.setValue(bar.maximum())
