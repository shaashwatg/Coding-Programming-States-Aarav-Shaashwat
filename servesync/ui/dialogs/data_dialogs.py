"""
Screens for data and trust: importing volunteers, backups, the change history,
and privacy (a volunteer's own data, and administrators handling requests).

The rules live in ``services/data_service.py``. These screens choose files,
show previews and lists, and always say what happened in plain words.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from servesync.core.errors import ServeSyncError, ValidationError
from servesync.core.i18n import format_clock, format_day, mark, tr, tr_n
from servesync.models import ChangeEntry, DeletionRequest, VolunteerStatus
from servesync.services import ImportPreview, ImportRow
from servesync.services.base import PUBLIC_FORM, WAITLIST
from servesync.services.data_service import json_text, template_csv
from servesync.ui.context import AppContext
from servesync.ui.dialogs.coordination_dialogs import ask_save_path
from servesync.ui.report_files import save_text
from servesync.ui.widgets.common import (
    EnumComboBox,
    Panel,
    clear_layout,
    confirm,
    guarded,
    make_button,
    make_label,
)
from servesync.ui.widgets.table import Column, RecordTable

# ------------------------------------------------------------ change wording

_ACTIONS = {
    "ADDED": mark("Added"),
    "CHANGED": mark("Changed"),
    "REMOVED": mark("Removed"),
    "STATUS": mark("Status changed"),
    "IMPORTED": mark("Imported"),
    "RESTORED": mark("Restored a backup"),
    "ANONYMIZED": mark("Removed personal details"),
    "REQUESTED": mark("Asked for deletion"),
}
_ENTITIES = {
    "VOLUNTEER": mark("Volunteer"),
    "PROGRAM": mark("Program"),
    "SHIFT": mark("Shift"),
    "SIGN_UP": mark("Sign-up"),
    "ACCOUNT": mark("Account"),
    "SETTINGS": mark("Settings"),
    "DATA": mark("Data"),
}
#: Field names in the history, as people would say them.
_FIELDS = {
    "first_name": mark("first name"),
    "last_name": mark("last name"),
    "preferred_name": mark("name they go by"),
    "pronouns": mark("pronouns"),
    "email": mark("email"),
    "phone": mark("phone"),
    "birth_date": mark("birth date"),
    "recruitment_source": mark("how they heard"),
    "skills": mark("skills"),
    "availability": mark("availability"),
    "emergency_contact_name": mark("emergency contact"),
    "emergency_contact_phone": mark("emergency phone"),
    "notes": mark("notes"),
    "access_needs": mark("access needs"),
    "referred_by": mark("referred by"),
    "title": mark("title"),
    "description": mark("description"),
    "category": mark("category"),
    "location": mark("location"),
    "coordinator_name": mark("coordinator"),
    "min_age": mark("minimum age"),
    "required_skills": mark("skills"),
    "story_video_url": mark("story video"),
    "access_features": mark("access"),
    "impact_unit": mark("what it measures"),
    "required_certifications": mark("required certifications"),
    "starts_at": mark("start time"),
    "ends_at": mark("end time"),
    "capacity": mark("spots"),
    "roles": mark("roles"),
    "role": mark("role"),
    "password": mark("password"),
    "organization": mark("organization details"),
    "backup": mark("backup"),
    "walk-in": mark("walk-in"),
    "deletion": mark("deletion"),
    "deletion declined": mark("deletion declined"),
}


def _status_word(code: str) -> str:
    from servesync.models.enums import _LABEL_OVERRIDES

    return tr(_LABEL_OVERRIDES.get(code, code.replace("_", " ").title()))


def describe_details(entry: ChangeEntry) -> str:
    """'phone, pronouns' or 'Active to Inactive', in the reader's language."""
    if entry.action == "STATUS" and ">" in entry.details:
        old, new = entry.details.split(">", 1)
        return tr("{old} to {new}", old=_status_word(old), new=_status_word(new))
    if entry.details.startswith("certifications: "):
        return tr("certification {name}", name=entry.details.removeprefix("certifications: "))
    if entry.action == "RESTORED":
        return tr("backup from {when}", when=entry.details) if entry.details else ""
    parts = [part.strip() for part in entry.details.split(",") if part.strip()]
    return ", ".join(tr(_FIELDS[part]) if part in _FIELDS else part for part in parts)


def describe_who(code: str) -> str:
    return {PUBLIC_FORM: tr("the application form"), WAITLIST: tr("the waitlist")}.get(code, code)


# ------------------------------------------------------------------- import


class ImportDialog(QDialog):
    """Choose a CSV, see every row checked, fix the file if needed, then import all at once."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._data: bytes | None = None
        self.preview: ImportPreview | None = None
        self.imported = 0
        self.setWindowTitle(tr("Import volunteers"))
        self.resize(980, 660)
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 16)
        column.setSpacing(16)
        column.addWidget(make_label(tr("Import volunteers"), "title"))
        column.addWidget(
            make_label(
                tr(
                    "Choose a CSV file saved from a spreadsheet. ServeSync checks every row first and lists exactly "
                    "what to fix. Nothing is saved until every row is ready. Start from the template to get the "
                    "column headings right."
                ),
                "subtitle",
                wrap=True,
            )
        )
        row = QHBoxLayout()
        row.addWidget(make_button(tr("Choose file…"), on_click=self._choose))
        row.addWidget(make_button(tr("Save template…"), on_click=self._template))
        row.addSpacing(24)
        row.addWidget(make_label(tr("Add them as"), "hint"))
        self.status: EnumComboBox[VolunteerStatus] = EnumComboBox(VolunteerStatus)
        self.status.removeItem(self.status.findData(VolunteerStatus.INACTIVE.value))
        self.status.set_value(VolunteerStatus.APPLICANT)
        self.status.setAccessibleName(tr("Add them as"))
        self.status.currentIndexChanged.connect(lambda _i: self._check())
        row.addWidget(self.status)
        row.addStretch(1)
        column.addLayout(row)
        self.summary = make_label(tr("No file chosen yet."), "muted", wrap=True)
        column.addWidget(self.summary)
        self.problems = make_label("", "banner-error", wrap=True)
        self.problems.hide()
        column.addWidget(self.problems)
        self.table: RecordTable[ImportRow] = RecordTable(
            [
                Column(tr("Line"), lambda r: r.line, align_right=True),
                Column(tr("Name"), lambda r: r.name),
                Column(tr("Email"), lambda r: r.email),
                Column(
                    tr("What to fix"),
                    lambda r: "; ".join(r.problems) or tr("Ready"),
                    tooltip=lambda r: "\n".join(r.problems) or tr("Ready"),
                    stretch=True,
                ),
            ],
            empty_message=tr("Rows will appear here once you choose a file."),
            accessible_name=tr("Import preview"),
        )
        column.addWidget(self.table, 1)
        # The full list for one row, readable without scrolling sideways.
        self.row_details = make_label("", "error", wrap=True, selectable=True)
        self.row_details.hide()
        column.addWidget(self.row_details)
        self.table.selection_changed.connect(self._show_row)
        buttons = QDialogButtonBox()
        self.import_button = make_button(tr("Import"), kind="primary", on_click=self._import)
        self.import_button.setEnabled(False)
        buttons.addButton(self.import_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)

    @guarded
    def _choose(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, tr("Choose a CSV file"), str(Path.home()), f"{tr('CSV spreadsheet')} (*.csv *.txt)"
        )
        if chosen:
            self.load(Path(chosen))

    def load(self, path: Path) -> None:
        try:
            self._data = path.read_bytes()
        except OSError:
            self._show_file_problem(
                tr("Couldn't open {name}. Check that the file isn't open elsewhere.", name=path.name)
            )
            return
        self._check()

    @guarded
    def _check(self) -> None:
        if self._data is None:
            return
        preview = self._ctx.services.data.preview_import(
            self._ctx.session, self._data, status=self.status.value() or VolunteerStatus.APPLICANT
        )
        self.preview = preview
        self.table.set_records(list(preview.rows))
        first_problem = next((i for i, row in enumerate(preview.rows) if not row.ready), None)
        if first_problem is not None:
            self.table.select_source_row(first_problem)
        else:
            self._show_row(None)
        if preview.file_problems:
            self._show_file_problem("\n".join(preview.file_problems))
        else:
            self.problems.hide()
        ready = sum(1 for row in preview.rows if row.ready)
        fixes = len(preview.rows) - ready
        text = tr_n("{count} row is ready.", "{count} rows are ready.", ready)
        if fixes:
            text += " " + tr_n(
                "{count} row needs fixing in the file before anything can be imported.",
                "{count} rows need fixing in the file before anything can be imported.",
                fixes,
            )
        if preview.notes:
            text += " " + " ".join(preview.notes)
        self.summary.setText(text)
        self.import_button.setEnabled(preview.ready)
        self.import_button.setText(tr_n("Import {count} volunteer", "Import {count} volunteers", ready))

    def _show_row(self, row: ImportRow | None) -> None:
        if row is None or row.ready:
            self.row_details.hide()
            return
        self.row_details.setText(tr("Line {line}: {problems}", line=row.line, problems="\n".join(row.problems)))
        self.row_details.show()

    def _show_file_problem(self, message: str) -> None:
        self.problems.setText(message)
        self.problems.show()
        self.import_button.setEnabled(False)

    @guarded
    def _template(self) -> None:
        path = ask_save_path(self, "volunteers-template.csv", tr("CSV spreadsheet"), "csv")
        if path is not None:
            save_text(template_csv(), path, excel=True)
            self._ctx.changed(tr("Saved {name}.", name=path.name))

    @guarded
    def _import(self) -> None:
        if self.preview is None:
            return
        self.imported = self._ctx.services.data.run_import(self._ctx.session, self.preview)
        self._ctx.changed(tr_n("Imported {count} volunteer.", "Imported {count} volunteers.", self.imported))
        self.accept()


# ----------------------------------------------------------- change history


class HistoryDialog(QDialog):
    """Who changed what, and when (administrators)."""

    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self.setWindowTitle(tr("Change history"))
        self.resize(1040, 680)
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 16)
        column.setSpacing(16)
        column.addWidget(make_label(tr("Change history"), "title"))
        column.addWidget(
            make_label(
                tr(
                    "Every change to records, newest first: who made it, when, and which details changed. The "
                    "history names fields but never copies their values, so it isn't a second copy of personal data."
                ),
                "subtitle",
                wrap=True,
            )
        )
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search by name or username"))
        self.search.setAccessibleName(tr("Search the history"))
        self.search.setMaxLength(80)
        self.search.textChanged.connect(lambda _t: self.reload())
        row.addWidget(self.search, 2)
        self.kind = QComboBox()
        self.kind.setAccessibleName(tr("Kind of record"))
        self.kind.addItem(tr("Every kind of record"), "")
        for code, label in _ENTITIES.items():
            self.kind.addItem(tr(label), code)
        self.kind.currentIndexChanged.connect(lambda _i: self.reload())
        row.addWidget(self.kind, 1)
        column.addLayout(row)
        self.table: RecordTable[ChangeEntry] = RecordTable(
            [
                Column(
                    tr("When"),
                    lambda e: f"{format_day(e.changed_at.date())}, {format_clock(e.changed_at)}",
                    sort=lambda e: e.changed_at,
                ),
                Column(tr("Who"), lambda e: describe_who(e.changed_by)),
                Column(
                    tr("What"),
                    lambda e: f"{tr(_ACTIONS.get(e.action, e.action))}: {tr(_ENTITIES.get(e.entity, e.entity))}",
                ),
                Column(tr("Record"), lambda e: e.label, stretch=True),
                Column(tr("Details"), describe_details),
            ],
            empty_message=tr("No changes match."),
            accessible_name=tr("Change history"),
            descending=True,
        )
        column.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)
        self.reload()

    @guarded
    def reload(self) -> None:
        self.table.set_records(
            self._ctx.services.data.history(
                self._ctx.session, entity=self.kind.currentData() or None, search=self.search.text()
            )
        )


# ------------------------------------------------------------------ privacy


class PrivacyRequestsPanel(Panel):
    """Pending deletion requests, for an administrator to complete or decline."""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(tr("Privacy requests"))
        self._ctx = ctx
        self.body.addWidget(
            make_label(
                tr(
                    "Volunteers can ask for their personal details to be removed. Completing a request deletes "
                    "someone with no service history; for anyone else it removes their details but keeps their "
                    "hours, so totals and reports still add up."
                ),
                "muted",
                wrap=True,
            )
        )
        self._rows = QVBoxLayout()
        self._rows.setSpacing(8)
        self.body.addLayout(self._rows)

    def refresh(self) -> None:
        clear_layout(self._rows)
        requests = self._ctx.services.data.deletion_requests(self._ctx.session)
        if not requests:
            self._rows.addWidget(make_label(tr("No requests are waiting."), "hint"))
        for request in requests:
            row = QHBoxLayout()
            text = tr(
                "{name} asked on {day}.",
                name=request.volunteer_name,
                day=format_day(request.requested_at.date()),
            )
            if request.reason:
                text += " " + tr("Reason: {reason}", reason=request.reason)
            row.addWidget(make_label(text, None, wrap=True), 1)
            row.addWidget(make_button(tr("Complete"), on_click=partial(self._complete, request)))
            row.addWidget(make_button(tr("Decline…"), on_click=partial(self._decline, request)))
            self._rows.addLayout(row)

    @guarded
    def _complete(self, request: DeletionRequest) -> None:
        if not confirm(
            self,
            tr("Remove personal details"),
            tr(
                "Remove {name}'s personal details? This can't be undone. Their sign-in stops working.",
                name=request.volunteer_name,
            ),
            tr("Remove details"),
        ):
            return
        deleted = self._ctx.services.data.complete_deletion(self._ctx.session, request.request_id)
        self._ctx.changed(
            tr("The record was deleted.") if deleted else tr("Personal details removed. Their hours still count.")
        )
        self.refresh()

    @guarded
    def _decline(self, request: DeletionRequest) -> None:
        reason, ok = QInputDialog.getMultiLineText(
            self, tr("Decline request"), tr("Tell {name} why (they will see this):", name=request.volunteer_name)
        )
        if not ok:
            return
        try:
            self._ctx.services.data.decline_deletion(self._ctx.session, request.request_id, reason)
        except ValidationError:
            self._ctx.changed(tr("Write a short reason so the volunteer understands."))
            return
        self._ctx.changed(tr("Request declined."))
        self.refresh()


class MyPrivacyPanel(Panel):
    """'Download my data' and 'Request deletion' on a volunteer's profile."""

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(tr("Your privacy"))
        self._ctx = ctx
        self.body.addWidget(
            make_label(
                tr(
                    "Download everything ServeSync holds about you, or ask for your personal details to be "
                    "removed. Your hours stay in the organization's totals, without your name."
                ),
                "muted",
                wrap=True,
            )
        )
        row = QHBoxLayout()
        self.download_button = make_button(tr("Download my data"), on_click=self._download)
        self.request_button = make_button(tr("Request deletion…"), kind="danger", on_click=self._request)
        row.addWidget(self.download_button)
        row.addWidget(self.request_button)
        row.addStretch(1)
        self.body.addLayout(row)
        self.status = make_label("", "hint", wrap=True)
        self.body.addWidget(self.status)

    def refresh(self) -> None:
        session = self._ctx.session
        latest = self._ctx.services.data.my_deletion_request(session, session.volunteer_id or 0)
        waiting = latest is not None and latest.status == "PENDING"
        self.request_button.setEnabled(not waiting)
        if latest is None:
            self.status.setText("")
        elif waiting:
            self.status.setText(
                tr("You asked on {day}. A coordinator will handle it soon.", day=format_day(latest.requested_at.date()))
            )
        elif latest.status == "DECLINED":
            self.status.setText(tr("Your request was declined: {reason}", reason=latest.response))
        else:
            self.status.setText("")

    @guarded
    def _download(self) -> None:
        session = self._ctx.session
        data = self._ctx.services.data.export_my_data(session, session.volunteer_id or 0)
        path = ask_save_path(self, "my-servesync-data.json", tr("Data file"), "json")
        if path is not None:
            save_text(json_text(data), path)
            self._ctx.changed(tr("Saved {name}.", name=path.name))

    @guarded
    def _request(self) -> None:
        reason, ok = QInputDialog.getMultiLineText(
            self,
            tr("Request deletion"),
            tr(
                "An administrator will remove your personal details and your sign-in. Your hours stay in the "
                "totals without your name. You may add a reason (optional):"
            ),
        )
        if not ok:
            return
        session = self._ctx.session
        try:
            self._ctx.services.data.request_deletion(session, session.volunteer_id or 0, reason)
        except ServeSyncError as error:
            self.status.setText(error.message)
            return
        self._ctx.changed(tr("Your request was sent."))
        self.refresh()
