"""
Add or edit a volunteer.

Two levels of validation meet here:
* **Prevention by design** — dates come from a calendar picker, choices from
  drop-down lists, so many mistakes simply can't be typed.
* **Validation with explanations** — everything else is checked by the
  Volunteer model (format *and* meaning) and every problem is shown next to
  its field at once. A common email typo ("gmial.com") gets a one-click fix.
"""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from servesync.core.i18n import tr
from servesync.core.validators import suggest_email_correction
from servesync.models import RecruitmentSource, Volunteer, VolunteerStatus
from servesync.services import Permission
from servesync.ui.context import AppContext
from servesync.ui.widgets.common import EnumComboBox, confirm, from_qdate, make_label, to_qdate
from servesync.ui.widgets.forms import AccessPicker, AvailabilityGrid, FormDialog, SkillPicker

#: Common pronouns offered as suggestions; anyone can type their own instead.
PRONOUN_SUGGESTIONS = ("", "she/her", "he/him", "they/them", "she/they", "he/they")


def _date_edit(maximum: QDate) -> QDateEdit:
    edit = QDateEdit()
    edit.setCalendarPopup(True)
    edit.setDisplayFormat("MM/dd/yyyy")
    edit.setMinimumDate(QDate(1900, 1, 1))
    edit.setMaximumDate(maximum)
    return edit


class VolunteerDialog(FormDialog):
    def __init__(self, ctx: AppContext, volunteer: Volunteer | None = None, parent: QWidget | None = None) -> None:
        self._ctx = ctx
        self._original = volunteer
        self._is_leader = ctx.session.can(Permission.MANAGE_VOLUNTEERS)
        editing_self = volunteer is not None and not self._is_leader
        title = (
            tr("Add volunteer")
            if volunteer is None
            else (tr("Edit my profile") if editing_self else tr("Edit volunteer"))
        )
        instructions = (
            tr("Fields marked * are required. Availability and skills help Smart Match suggest the right shifts.")
            if volunteer is None or self._is_leader
            else tr("Keep your contact details and availability current. Fields marked * are required.")
        )
        super().__init__(
            title, instructions, parent, save_text=tr("Add volunteer") if volunteer is None else tr("Save changes")
        )
        self.saved: Volunteer | None = None
        self._suggested: str | None = None
        today = QDate.currentDate()

        self.add_section(tr("Contact"))
        self.first_name = QLineEdit()
        self.first_name.setMaxLength(50)
        self.add_field("first_name", tr("First name *"), self.first_name)
        self.last_name = QLineEdit()
        self.last_name.setMaxLength(50)
        self.add_field("last_name", tr("Last name *"), self.last_name)
        self.preferred_name = QLineEdit()
        self.preferred_name.setMaxLength(50)
        self.add_field(
            "preferred_name",
            tr("Name they go by"),
            self.preferred_name,
            tr("Optional. Shown everywhere instead of the first name (e.g. a nickname or chosen name)."),
        )
        self.pronouns = QComboBox()
        self.pronouns.setEditable(True)
        self.pronouns.addItems(PRONOUN_SUGGESTIONS)
        self.pronouns.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        line = self.pronouns.lineEdit()
        if line is not None:
            line.setMaxLength(30)
            line.setPlaceholderText(tr("Optional — pick or type"))
        self.add_field("pronouns", tr("Pronouns"), self.pronouns, tr("Only shown if shared. ServeSync never guesses."))

        self.email = QLineEdit()
        self.email.setPlaceholderText("name@example.org")
        self.email.setMaxLength(254)
        email_box = QWidget()
        email_column = QVBoxLayout(email_box)
        email_column.setContentsMargins(0, 0, 0, 0)
        email_column.addWidget(self.email)
        suggestion_row = QHBoxLayout()
        self.suggestion = make_label("", "hint")
        self.use_suggestion = QPushButton(tr("Use it"))
        self.use_suggestion.setProperty("kind", "link")
        self.use_suggestion.clicked.connect(self._apply_suggestion)
        suggestion_row.addWidget(self.suggestion)
        suggestion_row.addWidget(self.use_suggestion)
        suggestion_row.addStretch(1)
        email_column.addLayout(suggestion_row)
        self.suggestion.hide()
        self.use_suggestion.hide()
        self.email.editingFinished.connect(self._check_email)
        self.add_field("email", tr("Email *"), email_box)
        self._fields["email"] = (self.email, self._fields["email"][1])  # errors highlight the input itself

        self.phone = QLineEdit()
        self.phone.setPlaceholderText("(206) 555-0142")
        self.phone.setMaxLength(25)
        self.add_field("phone", tr("Phone *"), self.phone, tr("U.S. or Canada number, any common format."))

        self.birth_date = _date_edit(today)
        self.birth_date.setDate(today.addYears(-18))
        self.add_field("birth_date", tr("Birth date *"), self.birth_date, tr("Volunteers must be at least 14."))

        self.add_section(tr("Emergency contact"))
        self.emergency_name = QLineEdit()
        self.emergency_name.setMaxLength(80)
        self.add_field(
            "emergency_contact_name",
            tr("Name"),
            self.emergency_name,
            tr("Required for volunteers under 18 (a parent or guardian)."),
        )
        self.emergency_phone = QLineEdit()
        self.emergency_phone.setMaxLength(25)
        self.add_field("emergency_contact_phone", tr("Phone"), self.emergency_phone)

        self.add_section(tr("How they can help"))
        self.skills = SkillPicker(ctx.services.volunteers.skill_names())
        self.add_field("skills", tr("Skills"), self.skills)
        self.availability = AvailabilityGrid()
        self.add_field("availability", tr("Usually available"), self.availability)

        self.add_section(tr("Access and support (optional)"))
        self.access = AccessPicker(for_program=False)
        self.add_field(
            "access_needs",
            tr("What helps"),
            self.access,
            tr("Used to suggest programs that fit and shown to coordinators. Never used to turn anyone away."),
        )

        self.status: EnumComboBox[VolunteerStatus] = EnumComboBox(VolunteerStatus)
        self.source: EnumComboBox[RecruitmentSource] = EnumComboBox(RecruitmentSource)
        self.joined_on = _date_edit(today)
        self.joined_on.setDate(today)
        self.notes = QPlainTextEdit()
        self.notes.setFixedHeight(80)
        if self._is_leader:
            self.add_section(tr("Recruitment (leaders only)"))
            self.add_field("recruitment_source", tr("How they heard about us"), self.source)
            self.add_field("joined_on", tr("Joined on"), self.joined_on)
            if volunteer is None:
                self.status.removeItem(
                    self.status.findData(VolunteerStatus.INACTIVE.value)
                )  # new people can't start archived
                self.add_field(
                    "status",
                    tr("Status"),
                    self.status,
                    tr("Applicants can't be scheduled until a leader approves them."),
                )
            self.add_field("notes", tr("Staff notes"), self.notes, tr("Visible to leaders only."))

        if volunteer is not None:
            self._load(volunteer)
        self.resize(720, 760)
        self.first_name.setFocus()

    # --------------------------------------------------------------- loading

    def _load(self, volunteer: Volunteer) -> None:
        self.first_name.setText(volunteer.first_name)
        self.last_name.setText(volunteer.last_name)
        self.preferred_name.setText(volunteer.preferred_name)
        self.pronouns.setEditText(volunteer.pronouns)
        self.access.set_values(volunteer.access_needs)
        self.email.setText(volunteer.email)
        self.phone.setText(volunteer.display_phone)
        self.birth_date.setDate(to_qdate(volunteer.birth_date))
        self.emergency_name.setText(volunteer.emergency_contact_name)
        self.emergency_phone.setText(volunteer.display_emergency_phone)
        self.skills.set_skills(volunteer.skills)
        self.availability.set_slots(volunteer.availability)
        self.source.set_value(volunteer.recruitment_source)
        self.joined_on.setDate(to_qdate(volunteer.joined_on))
        self.notes.setPlainText(volunteer.notes)

    def _check_email(self) -> None:
        fix = suggest_email_correction(self.email.text().strip())
        self.suggestion.setText(tr("Did you mean {fix}?", fix=fix) if fix else "")
        self.suggestion.setVisible(bool(fix))
        self.use_suggestion.setVisible(bool(fix))
        self._suggested = fix

    def _apply_suggestion(self) -> None:
        if self._suggested:
            self.email.setText(self._suggested)
            self._check_email()

    # ---------------------------------------------------------------- saving

    def _build(self) -> Volunteer:
        original = self._original
        status = self.status.value() if original is None and self._is_leader else None
        return Volunteer(
            first_name=self.first_name.text(),
            last_name=self.last_name.text(),
            email=self.email.text(),
            phone=self.phone.text(),
            birth_date=from_qdate(self.birth_date.date()),
            joined_on=(
                from_qdate(self.joined_on.date())
                if self._is_leader
                else (original.joined_on if original else from_qdate(QDate.currentDate()))
            ),
            status=status or (original.status if original else VolunteerStatus.APPLICANT),
            recruitment_source=(
                self.source.value() or RecruitmentSource.OTHER
                if self._is_leader
                else (original.recruitment_source if original else RecruitmentSource.OTHER)
            ),
            skills=self.skills.skills(),
            availability=self.availability.slots(),
            emergency_contact_name=self.emergency_name.text(),
            emergency_contact_phone=self.emergency_phone.text(),
            notes=self.notes.toPlainText() if self._is_leader else (original.notes if original else ""),
            preferred_name=self.preferred_name.text(),
            pronouns=self.pronouns.currentText(),
            access_needs=self.access.values(),
            volunteer_id=original.volunteer_id if original else None,
        )

    def submit(self) -> bool:
        volunteer = self._build()  # raises ValidationError -> shown beside each field
        services, session = self._ctx.services, self._ctx.session
        if self._original is None:
            duplicates = services.volunteers.possible_duplicates(session, volunteer)
            if duplicates:
                names = ", ".join(f"{d.full_name} ({d.email})" for d in duplicates[:3])
                if not confirm(
                    self,
                    tr("Possible duplicate"),
                    tr(("This looks like someone already on file: {names}.\n\nAdd a new record anyway?"), names=names),
                    tr("Add anyway"),
                ):
                    return False
            self.saved = services.volunteers.register(session, volunteer)
        else:
            self.saved = services.volunteers.update_profile(session, volunteer)
        return True
