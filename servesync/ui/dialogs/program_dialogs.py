"""Add or edit a program (opportunity) and its shifts."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from servesync.config import MAX_SHIFT_CAPACITY, MINIMUM_VOLUNTEER_AGE
from servesync.core.errors import ValidationError
from servesync.models import Opportunity, OpportunityCategory, OpportunityStatus, Shift
from servesync.ui.context import AppContext
from servesync.ui.photos import prepare_photo
from servesync.ui.widgets.common import (
    BusyCursor,
    EnumComboBox,
    from_qdate,
    from_qtime,
    make_button,
    to_qdate,
    to_qtime,
)
from servesync.ui.widgets.forms import AccessPicker, FormDialog, SkillPicker
from servesync.ui.widgets.visuals import ProgramArt


class OpportunityDialog(FormDialog):
    def __init__(self, ctx: AppContext, opportunity: Opportunity | None = None, parent: QWidget | None = None) -> None:
        creating = opportunity is None
        super().__init__(
            "New program" if creating else "Edit program",
            "Describe the work so volunteers know what to expect. Fields marked * are required.",
            parent,
            save_text="Create program" if creating else "Save changes",
        )
        self._ctx = ctx
        self._original = opportunity
        self.saved: Opportunity | None = None
        self._photo: bytes | None = None
        self._photo_changed = False

        self.title_edit = QLineEdit()
        self.title_edit.setMaxLength(80)
        self.add_field("title", "Title *", self.title_edit)
        self.category: EnumComboBox[OpportunityCategory] = EnumComboBox(OpportunityCategory)
        self.add_field("category", "Category *", self.category)
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(90)
        self.add_field("description", "What volunteers will do *", self.description, "Two or three short sentences.")
        self.location = QLineEdit()
        self.location.setMaxLength(120)
        self.add_field("location", "Location *", self.location)
        self.coordinator = QLineEdit()
        self.coordinator.setMaxLength(80)
        self.add_field("coordinator_name", "Coordinator *", self.coordinator)
        self.min_age = QSpinBox()
        self.min_age.setRange(MINIMUM_VOLUNTEER_AGE, 99)
        self.min_age.setSuffix(" years")
        self.add_field("min_age", "Minimum age", self.min_age, "Raise it for work like driving or construction.")
        self.skills = SkillPicker(ctx.services.volunteers.skill_names())
        self.add_field(
            "required_skills", "Helpful skills", self.skills, "Smart Match favors volunteers who have these."
        )
        self.access = AccessPicker(for_program=True)
        self.add_field(
            "access_features",
            "Access and support",
            self.access,
            "Tick what this program offers. Volunteers who need these see it first.",
        )

        self.add_section("Photo and story")
        photo_box = QWidget()
        photo_row = QHBoxLayout(photo_box)
        photo_row.setContentsMargins(0, 0, 0, 0)
        self.art = ProgramArt(200, 128)
        photo_row.addWidget(self.art)
        buttons = QVBoxLayout()
        buttons.addWidget(make_button("Choose photo...", on_click=self._choose_photo))
        self.remove_photo_button = make_button("Remove photo", on_click=self._remove_photo)
        buttons.addWidget(self.remove_photo_button)
        buttons.addStretch(1)
        photo_row.addLayout(buttons)
        photo_row.addStretch(1)
        self.add_field(
            "photo",
            "Program photo",
            photo_box,
            "Use your own photo of this program. ServeSync resizes it to under 300 kB automatically.",
        )
        self.story = QLineEdit()
        self.story.setPlaceholderText("https://")
        self.story.setMaxLength(300)
        self.add_field(
            "story_video_url",
            "Story video link",
            self.story,
            "Optional. Opens in the browser only when someone chooses to watch it; nothing plays automatically.",
        )
        self.publish = QCheckBox("Open for sign-ups right away")
        if creating:
            self.add_field("status", "Publish", self.publish, "Leave unchecked to keep it as a draft while you plan.")

        if opportunity is not None:
            self.title_edit.setText(opportunity.title)
            self.category.set_value(opportunity.category)
            self.description.setPlainText(opportunity.description)
            self.location.setText(opportunity.location)
            self.coordinator.setText(opportunity.coordinator_name)
            self.min_age.setValue(opportunity.min_age)
            self.skills.set_skills(opportunity.required_skills)
            self.access.set_values(opportunity.access_features)
            self.story.setText(opportunity.story_video_url)
            if opportunity.opportunity_id is not None:
                self._photo = ctx.services.opportunities.photo(ctx.session, opportunity.opportunity_id)
        self.category.currentIndexChanged.connect(lambda _index: self._refresh_art())
        self._refresh_art()
        self.resize(700, 780)

    def _refresh_art(self) -> None:
        category = self.category.value() or OpportunityCategory.ADMINISTRATIVE
        self.art.show_program(category, self._photo, self.title_edit.text() or "this program")
        self.remove_photo_button.setEnabled(self._photo is not None)

    def _choose_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a program photo", "", "Pictures (*.jpg *.jpeg *.png *.heic *.webp)"
        )
        if not path:
            return
        try:
            with BusyCursor():
                self._photo = prepare_photo(path)
        except ValidationError as error:
            self.show_errors(error)
            return
        self._photo_changed = True
        self.clear_errors()
        self._refresh_art()

    def _remove_photo(self) -> None:
        self._photo = None
        self._photo_changed = True
        self._refresh_art()

    def submit(self) -> bool:
        original = self._original
        opportunity = Opportunity(
            title=self.title_edit.text(),
            description=self.description.toPlainText(),
            category=self.category.value() or OpportunityCategory.ADMINISTRATIVE,
            location=self.location.text(),
            coordinator_name=self.coordinator.text(),
            min_age=self.min_age.value(),
            status=original.status if original else OpportunityStatus.DRAFT,
            required_skills=self.skills.skills(),
            story_video_url=self.story.text(),
            access_features=self.access.values(),
            opportunity_id=original.opportunity_id if original else None,
        )
        services, session = self._ctx.services, self._ctx.session
        if original is None:
            saved = services.opportunities.create(session, opportunity)
            if self.publish.isChecked() and saved.opportunity_id is not None:
                services.opportunities.change_status(session, saved.opportunity_id, OpportunityStatus.OPEN)
        else:
            saved = services.opportunities.update(session, opportunity)
        if self._photo_changed and saved.opportunity_id is not None:
            if self._photo is None:
                services.opportunities.remove_photo(session, saved.opportunity_id)
            else:
                services.opportunities.set_photo(session, saved.opportunity_id, self._photo)
        self.saved = saved
        return True


class ShiftDialog(FormDialog):
    """Create one shift (optionally repeating weekly) or edit an existing one."""

    def __init__(
        self, ctx: AppContext, opportunity: Opportunity, shift: Shift | None = None, parent: QWidget | None = None
    ) -> None:
        creating = shift is None
        super().__init__(
            "Add shifts" if creating else "Edit shift",
            f"For {opportunity.title}. Shifts must start in the future and last up to 12 hours.",
            parent,
            save_text="Add shifts" if creating else "Save changes",
        )
        self._ctx = ctx
        self._opportunity = opportunity
        self._original = shift
        self.created = 0

        tomorrow = QDate.currentDate().addDays(1)
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("ddd MM/dd/yyyy")
        self.day.setMinimumDate(QDate.currentDate())
        self.day.setDate(tomorrow)
        self.add_field("day", "Date", self.day)
        self.start = QTimeEdit(QTime(9, 0))
        self.start.setDisplayFormat("h:mm AP")
        self.add_field("starts_at", "Starts", self.start)
        self.end = QTimeEdit(QTime(12, 0))
        self.end.setDisplayFormat("h:mm AP")
        self.add_field("ends_at", "Ends", self.end)
        self.capacity = QSpinBox()
        self.capacity.setRange(1, MAX_SHIFT_CAPACITY)
        self.capacity.setValue(6)
        self.capacity.setSuffix(" volunteers")
        self.add_field("capacity", "Volunteers needed", self.capacity)
        self.notes = QLineEdit()
        self.notes.setMaxLength(300)
        self.notes.setPlaceholderText("for example, wear closed-toe shoes")
        self.add_field("notes", "Notes for volunteers", self.notes)
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 52)
        self.repeat.setValue(1)
        self.repeat.setSuffix(" week(s)")
        if shift is None:
            self.add_field("occurrences", "Repeat weekly for", self.repeat, "1 means just this date. Up to 52 weeks.")
        else:
            self.day.setDate(to_qdate(shift.starts_at.date()))
            self.start.setTime(to_qtime(shift.starts_at.time()))
            self.end.setTime(to_qtime(shift.ends_at.time()))
            self.capacity.setValue(shift.capacity)
            self.notes.setText(shift.notes)
        self.resize(560, 520)

    def submit(self) -> bool:
        day = from_qdate(self.day.date())
        starts = datetime.combine(day, from_qtime(self.start.time()))
        ends = datetime.combine(day, from_qtime(self.end.time()))
        shift = Shift(
            opportunity_id=self._opportunity.opportunity_id or 0,
            starts_at=starts,
            ends_at=ends,
            capacity=self.capacity.value(),
            notes=self.notes.text(),
            shift_id=self._original.shift_id if self._original else None,
        )
        services, session = self._ctx.services, self._ctx.session
        if self._original is None:
            self.created = len(services.opportunities.add_weekly_shifts(session, shift, self.repeat.value()))
        else:
            services.opportunities.update_shift(session, shift)
        return True
