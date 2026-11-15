"""
Milestone certificates (for volunteers) and "Verify a record" (for leaders).

Rules and codes live in ``services/records_service.py``; these screens show
what's earned, save certificates as PDFs, and check a code someone reads out.
"""

from __future__ import annotations

from functools import partial

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from servesync.core.errors import ServeSyncError, ValidationError
from servesync.core.i18n import format_day, tr
from servesync.services.records_service import MILESTONES, display_code
from servesync.ui.context import AppContext
from servesync.ui.dialogs.coordination_dialogs import ask_save_path
from servesync.ui.report_files import save_html_pdf
from servesync.ui.widgets.common import Panel, clear_layout, format_hours, guarded, make_button, make_label, set_prop


class CertificatesPanel(Panel):
    """25, 50 and 100 hours: what's been reached (with a certificate to save) and what's next."""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(tr("Milestone certificates"))
        self._ctx = ctx
        self.body.addWidget(
            make_label(
                tr("Each certificate has a code, so a school or employer can ask us to confirm it."), "muted", wrap=True
            )
        )
        self._rows = QVBoxLayout()
        self._rows.setSpacing(8)
        self.body.addLayout(self._rows)

    def refresh(self) -> None:
        clear_layout(self._rows)
        services, session = self._ctx.services, self._ctx.session
        volunteer_id = session.volunteer_id or 0
        reached = {m.hours: m for m in services.records.milestones(session, volunteer_id)}
        total = services.volunteers.participation(session, volunteer_id).total_hours
        for hours in MILESTONES:
            row = QHBoxLayout()
            row.setSpacing(16)
            milestone = reached.get(hours)
            if milestone is not None:
                label = make_label(
                    tr("{hours} hours: reached {day}", hours=hours, day=format_day(milestone.reached_on)), "ok"
                )
                row.addWidget(label)
                button = make_button(tr("Save certificate"), on_click=partial(self._save, hours))
                button.setAccessibleName(tr("Save the {hours}-hour certificate", hours=hours))
                row.addWidget(button)
            else:
                row.addWidget(
                    make_label(
                        tr("{hours} hours: {left} to go", hours=hours, left=format_hours(max(hours - total, 0))),
                        "muted",
                    )
                )
            row.addStretch(1)
            self._rows.addLayout(row)

    @guarded
    def _save(self, hours: int) -> None:
        session = self._ctx.session
        path = ask_save_path(self, f"certificate-{hours}-hours.pdf", tr("PDF document"), "pdf")
        if path is None:
            return
        code, html = self._ctx.services.records.milestone_certificate(session, session.volunteer_id or 0, hours)
        save_html_pdf(html, path, tr("Certificate of service"))
        self._ctx.changed(tr("Saved {name}. Its code is {code}.", name=path.name, code=display_code(code)))


class VerifyDialog(QDialog):
    """Check the code printed on a service record or certificate."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self.setWindowTitle(tr("Verify a record"))
        self.resize(600, 420)
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 16)
        column.setSpacing(16)
        column.addWidget(make_label(tr("Verify a record"), "title"))
        column.addWidget(
            make_label(
                tr(
                    "Someone sent you a service record or certificate and wants to know it's genuine? Type the "
                    "code printed at the bottom."
                ),
                "subtitle",
                wrap=True,
            )
        )
        row = QHBoxLayout()
        self.code = QLineEdit()
        self.code.setPlaceholderText(tr("For example, K7Q2-9XFM"))
        self.code.setAccessibleName(tr("Verification code"))
        self.code.setMaxLength(20)
        self.code.returnPressed.connect(self.check)
        row.addWidget(self.code, 1)
        self.check_button = make_button(tr("Check"), kind="primary", on_click=self.check)
        row.addWidget(self.check_button)
        column.addLayout(row)
        self.problem = make_label("", "error", wrap=True)
        self.problem.hide()
        column.addWidget(self.problem)
        self.answer = make_label("", "lead", wrap=True, selectable=True)
        column.addWidget(self.answer)
        column.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)

    def check(self) -> None:
        self.problem.hide()
        self.answer.setText("")
        set_prop(self.code, "invalid", False)
        try:
            outcome = self._ctx.services.records.verify(self._ctx.session, self.code.text())
        except ValidationError as error:
            self._problem(" ".join(error.errors.values()))
            return
        except ServeSyncError as error:
            self._problem(error.message)
            return
        document = outcome.document
        if document is None:
            self._problem(
                tr("No record with this code was issued by this organization. It may be mistyped, or not genuine.")
            )
            return
        if document.kind == "MILESTONE":
            what = tr("a {hours}-hour certificate", hours=document.milestone)
        else:
            what = tr(
                "a service record for {start} to {end}, showing {hours}",
                start=format_day(document.period_start) if document.period_start else "",
                end=format_day(document.period_end) if document.period_end else "",
                hours=format_hours(document.hours),
            )
        text = tr(
            "Genuine. {code} is {what} for {name}, issued {day} by {who}.",
            code=display_code(document.code),
            what=what,
            name=document.volunteer_name,
            day=format_day(document.issued_at.date()),
            who=document.issued_by,
        )
        if outcome.changed_since and outcome.current_hours is not None:
            text += " " + tr(
                "Hours for that period have since been corrected to {hours}.",
                hours=format_hours(outcome.current_hours),
            )
        set_prop(self.answer, "role", "ok")
        self.answer.setText(text)
        self._ctx.announce(text)

    def _problem(self, message: str) -> None:
        self.problem.setText(message)
        self.problem.show()
        set_prop(self.code, "invalid", True)
        self._ctx.announce(message)
