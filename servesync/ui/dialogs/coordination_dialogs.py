"""
Screens for coordinating people: post an announcement, tomorrow's reminder list,
and saving a shift as a calendar file or a paper sign-in sheet.

The rules live in ``services/coordination_service.py``; these screens only collect
input, show results, and ask where to save files.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from servesync.core.errors import ServeSyncError, ValidationError
from servesync.core.i18n import format_clock, format_long_day, tr, tr_n
from servesync.services import ReminderRow
from servesync.services.coordination_service import ANNOUNCEMENT_MAX_LENGTH, reminders_csv
from servesync.ui.context import AppContext
from servesync.ui.report_files import save_html_pdf, save_text
from servesync.ui.widgets.common import from_qdate, guarded, make_button, make_label, set_prop, to_qdate
from servesync.ui.widgets.table import Column, RecordTable


def ask_save_path(parent: QWidget, filename: str, description: str, extension: str) -> Path | None:
    """Ask where to save, starting in Documents; always returns a path with the right extension."""
    start = Path.home() / "Documents" / filename
    chosen, _ = QFileDialog.getSaveFileName(
        parent, tr("Save {description}", description=description), str(start), f"{description} (*.{extension})"
    )
    if not chosen:
        return None
    path = Path(chosen)
    return path if path.suffix.lower() == f".{extension}" else path.with_suffix(f".{extension}")


def save_calendar_file(ctx: AppContext, shift_id: int, parent: QWidget) -> None:
    """'Add to calendar': save the shift as a standard .ics file any calendar app can open."""
    name, text = ctx.services.coordination.calendar_file(ctx.session, shift_id)
    path = ask_save_path(parent, name, tr("Calendar event"), "ics")
    if path is None:
        return
    save_text(text, path)
    ctx.changed(tr("Saved {name}. Open it to add the shift to your calendar.", name=path.name))


def save_sign_in_sheet(ctx: AppContext, shift_id: int, parent: QWidget) -> None:
    """A printable paper sign-in sheet, the fallback for a day without the laptop."""
    html = ctx.services.coordination.sign_in_sheet(ctx.session, shift_id)
    overview = ctx.services.opportunities.shift_overview(ctx.session, shift_id)
    name = f"sign-in-sheet-{overview.shift.starts_at:%Y-%m-%d}.pdf"
    path = ask_save_path(parent, name, tr("PDF document"), "pdf")
    if path is None:
        return
    save_html_pdf(html, path, tr("Sign-in sheet"))
    ctx.changed(tr("Saved {name}.", name=path.name))


class AnnounceDialog(QDialog):
    """Write a short note for everyone signed up for a program or a shift."""

    def __init__(
        self,
        ctx: AppContext,
        target: str,
        *,
        opportunity_id: int | None = None,
        shift_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._opportunity_id, self._shift_id = opportunity_id, shift_id
        self.setWindowTitle(tr("Post an announcement"))
        self.resize(620, 460)
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 16)
        column.setSpacing(16)
        column.addWidget(make_label(tr("Post an announcement"), "title"))
        column.addWidget(
            make_label(
                tr(
                    "Everyone signed up for {target} sees this on their Home page. ServeSync doesn't send "
                    "texts or emails; use Tomorrow's reminders for a call list.",
                    target=target,
                ),
                "subtitle",
                wrap=True,
            )
        )
        self.error = make_label("", "error", wrap=True)
        self.error.hide()
        self.text = QPlainTextEdit()
        self.text.setAccessibleName(tr("Announcement"))
        self.text.setPlaceholderText(tr("For example: Parking is in the north lot this week."))
        self.text.textChanged.connect(self._count)
        column.addWidget(self.text, 1)
        self.counter = make_label("", "hint")
        column.addWidget(self.counter)
        column.addWidget(self.error)
        previous = ctx.services.coordination.announcements(
            ctx.session, opportunity_id=opportunity_id, shift_id=shift_id
        )
        if previous:
            column.addWidget(
                make_label(
                    tr_n(
                        "{count} earlier announcement. Latest: {body}",
                        "{count} earlier announcements. Latest: {body}",
                        len(previous),
                        body=previous[0].body,
                    ),
                    "hint",
                    wrap=True,
                )
            )
        buttons = QDialogButtonBox()
        post = QPushButton(tr("Post"))
        post.setProperty("kind", "primary")
        buttons.addButton(post, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._post)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)
        self._count()

    def _count(self) -> None:
        used = len(self.text.toPlainText())
        self.counter.setText(tr("{used} of {limit} characters", used=used, limit=ANNOUNCEMENT_MAX_LENGTH))

    def _post(self) -> None:
        try:
            self._ctx.services.coordination.post_announcement(
                self._ctx.session,
                self.text.toPlainText(),
                opportunity_id=self._opportunity_id,
                shift_id=self._shift_id,
            )
        except ValidationError as error:
            self._show(" ".join(error.errors.values()))
            return
        except ServeSyncError as error:
            self._show(error.message)
            return
        self._ctx.changed(tr("Announcement posted."))
        self.accept()

    def _show(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()
        set_prop(self.text, "invalid", True)
        self.text.setFocus()


class RemindersDialog(QDialog):
    """A call list for the next day's shifts, to export for a texting or email service."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._rows: list[ReminderRow] = []
        self.setWindowTitle(tr("Tomorrow's reminders"))
        self.resize(1040, 640)
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 16)
        column.setSpacing(16)
        column.addWidget(make_label(tr("Tomorrow's reminders"), "title"))
        column.addWidget(
            make_label(
                tr(
                    "Everyone signed up for a shift on this day, with how to reach them. A reminder the day "
                    "before is the simplest way to cut no-shows. Export the list for a texting or email service."
                ),
                "subtitle",
                wrap=True,
            )
        )
        row = QHBoxLayout()
        row.addWidget(make_label(tr("Day"), "hint"))
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("MM/dd/yyyy")
        today = ctx.services.clock.now().date()
        self.day.setMinimumDate(to_qdate(today))
        self.day.setMaximumDate(QDate(to_qdate(today)).addDays(60))
        self.day.setDate(to_qdate(today).addDays(1))
        self.day.setAccessibleName(tr("Day"))
        self.day.dateChanged.connect(lambda _date: self.reload())
        row.addWidget(self.day)
        row.addStretch(1)
        self.summary = make_label("", "muted")
        row.addWidget(self.summary)
        column.addLayout(row)
        self.table: RecordTable[ReminderRow] = RecordTable(
            [
                Column(
                    tr("Time"),
                    lambda r: f"{format_clock(r.starts_at)} – {format_clock(r.ends_at)}",
                    sort=lambda r: r.starts_at,
                ),
                Column(tr("Volunteer"), lambda r: r.volunteer_name, stretch=True),
                Column(tr("Phone"), lambda r: r.phone),
                Column(tr("Email"), lambda r: r.email),
                Column(tr("Program"), lambda r: r.program),
                Column(tr("Role"), lambda r: r.role),
            ],
            empty_message=tr("Nobody is signed up for a shift on this day."),
            accessible_name=tr("Tomorrow's reminders"),
        )
        column.addWidget(self.table, 1)
        buttons = QDialogButtonBox()
        self.export_button = make_button(tr("Export CSV"), kind="primary", on_click=self._export)
        buttons.addButton(self.export_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)
        self.reload()

    @guarded
    def reload(self) -> None:
        day = from_qdate(self.day.date())
        self._rows = self._ctx.services.coordination.reminders(self._ctx.session, day)
        self.table.set_records(self._rows)
        self.summary.setText(
            tr_n(
                "{count} person to remind for {day}",
                "{count} people to remind for {day}",
                len(self._rows),
                day=format_long_day(day),
            )
        )
        self.export_button.setEnabled(bool(self._rows))

    @guarded
    def _export(self) -> None:
        day = from_qdate(self.day.date())
        path = ask_save_path(self, f"reminders-{day:%Y-%m-%d}.csv", tr("CSV spreadsheet"), "csv")
        if path is None:
            return
        save_text(reminders_csv(self._rows), path, excel=True)
        self._ctx.changed(tr("Saved {name}.", name=path.name))
