"""
Become a volunteer: the public front door, reached from the sign-in screen.

Anyone may fill this in without an account, so it only ever creates an Applicant
for a leader to review. Validation is the same as everywhere else, because the
Volunteer model checks itself; the form adds the "who invited you?" question.
"""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit, QLineEdit, QWidget

from servesync.core.i18n import tr
from servesync.models import RecruitmentSource, Volunteer
from servesync.services import Services
from servesync.ui.widgets.common import EnumComboBox, from_qdate, inform
from servesync.ui.widgets.forms import AccessPicker, AvailabilityGrid, FormDialog, SkillPicker


class ApplicationDialog(FormDialog):
    def __init__(self, services: Services, parent: QWidget | None = None) -> None:
        super().__init__(
            tr("Become a volunteer"),
            tr(
                "Tell us about yourself. A coordinator will review this and give you a sign-in. "
                "Fields marked * are required."
            ),
            parent,
            save_text=tr("Send application"),
        )
        self._services = services
        self.saved: Volunteer | None = None
        today = QDate.currentDate()

        self.add_section(tr("About you"))
        self.first_name = self._text_field("first_name", tr("First name *"), 50)
        self.last_name = self._text_field("last_name", tr("Last name *"), 50)
        self.preferred_name = self._text_field(
            "preferred_name", tr("Name you go by"), 50, tr("Optional. We'll use this instead of your first name.")
        )
        self.pronouns = self._text_field("pronouns", tr("Pronouns"), 30, tr("Optional. Only shown if you share them."))
        self.email = self._text_field("email", tr("Email *"), 254)
        self.phone = self._text_field("phone", tr("Phone *"), 25, tr("U.S. or Canada number, any common format."))
        self.birth_date = QDateEdit()
        self.birth_date.setCalendarPopup(True)
        self.birth_date.setDisplayFormat("MM/dd/yyyy")
        self.birth_date.setMinimumDate(QDate(1900, 1, 1))
        self.birth_date.setMaximumDate(today)
        self.birth_date.setDate(today.addYears(-18))
        self.add_field("birth_date", tr("Birth date *"), self.birth_date, tr("Volunteers must be at least 14."))

        # Under 18, this contact must be a parent or guardian; the Volunteer model enforces it.
        self.add_section(tr("Parent, guardian, or emergency contact"))
        self.emergency_name = self._text_field(
            "emergency_contact_name",
            tr("Name"),
            80,
            tr("If you are under 18, this must be your parent or guardian. Otherwise optional."),
        )
        self.emergency_phone = self._text_field("emergency_contact_phone", tr("Phone"), 25)

        self.add_section(tr("How you can help"))
        self.skills = SkillPicker(services.volunteers.skill_names())
        self.add_field("skills", tr("Skills"), self.skills)
        self.availability = AvailabilityGrid()
        self.add_field("availability", tr("Usually available"), self.availability)
        self.access = AccessPicker(for_program=False)
        self.add_field(
            "access_needs",
            tr("What helps"),
            self.access,
            tr("Optional. Used to suggest programs that fit. Never used to turn anyone away."),
        )

        self.add_section(tr("How you found us"))
        self.source: EnumComboBox[RecruitmentSource] = EnumComboBox(RecruitmentSource)
        self.add_field("recruitment_source", tr("How did you hear about us?"), self.source)
        self.referred_by = self._text_field(
            "referred_by", tr("Who invited you?"), 101, tr("Optional. We'd like to thank them.")
        )

        self.resize(720, 760)
        self.first_name.setFocus()

    def _text_field(self, name: str, label: str, max_length: int, hint: str = "") -> QLineEdit:
        field = QLineEdit()
        field.setMaxLength(max_length)
        self.add_field(name, label, field, hint)
        return field

    def submit(self) -> bool:
        application = Volunteer(  # raises ValidationError -> shown beside each field
            first_name=self.first_name.text(),
            last_name=self.last_name.text(),
            email=self.email.text(),
            phone=self.phone.text(),
            birth_date=from_qdate(self.birth_date.date()),
            recruitment_source=self.source.value() or RecruitmentSource.OTHER,
            skills=self.skills.skills(),
            availability=self.availability.slots(),
            emergency_contact_name=self.emergency_name.text(),
            emergency_contact_phone=self.emergency_phone.text(),
            preferred_name=self.preferred_name.text(),
            pronouns=self.pronouns.text(),
            access_needs=self.access.values(),
            referred_by=self.referred_by.text(),
        )
        self.saved = self._services.volunteers.apply(application)
        inform(
            self,
            tr("Application received"),
            tr(
                "Thank you, {name}! A coordinator will review your application and give you a sign-in.",
                name=self.saved.given_name,
            ),
        )
        return True
