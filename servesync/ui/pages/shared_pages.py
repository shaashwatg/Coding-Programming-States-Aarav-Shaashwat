"""
Pages used by every role: the shift calendar and settings.

The calendar is the app's "event calendar": a month view marked with dots
(marigold when a day still has open spots), with that day's shifts beside it.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from servesync.models import Appearance, MessageDuration, ShiftOverview, Theme
from servesync.services import Permission
from servesync.ui.context import AppContext
from servesync.ui.dialogs.auth_dialogs import ChangePasswordDialog
from servesync.ui.pages.base import Page
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import (
    EnumComboBox,
    PageHeader,
    Panel,
    format_date,
    from_qdate,
    guarded,
    make_button,
    make_label,
    to_qdate,
)
from servesync.ui.widgets.shift_panel import ShiftInfoPanel
from servesync.ui.widgets.table import Column, RecordTable
from servesync.ui.widgets.visuals import ShiftCalendar

TEXT_SIZES = (0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)


def _clock(moment: datetime) -> str:
    return f"{moment.hour % 12 or 12}:{moment:%M} {'AM' if moment.hour < 12 else 'PM'}"


class CalendarPage(Page):
    key = "calendar"
    title = "Calendar"
    icon_name = "calendar-days"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self._month_shifts: list[ShiftOverview] = []
        leader = ctx.session.can(Permission.MANAGE_SCHEDULE)
        self.layout_.addWidget(
            PageHeader(
                "Calendar",
                "Dots mark days with shifts; marigold dots still have open spots. Pick a day to see its shifts."
                if leader
                else "Dots mark days with open shifts. Pick a day, then a shift, to see details and sign up.",
            )
        )
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_column = QVBoxLayout(left)
        left_column.setContentsMargins(0, 0, 12, 0)
        self.calendar = ShiftCalendar()
        self.calendar.setMinimumHeight(330)
        self.calendar.selectionChanged.connect(self._show_day)
        self.calendar.currentPageChanged.connect(lambda _y, _m: self.reload())
        left_column.addWidget(self.calendar)
        self.day_title = make_label("", "section")
        left_column.addWidget(self.day_title)
        self.day_table: RecordTable[ShiftOverview] = RecordTable(
            [
                Column(
                    "Time",
                    lambda o: f"{_clock(o.shift.starts_at)} – {_clock(o.shift.ends_at)}",
                    sort=lambda o: o.shift.starts_at,
                ),
                Column("Program", lambda o: o.opportunity_title, stretch=True),
                Column(
                    "Spots open",
                    lambda o: o.open_spots,
                    color=lambda o: current_palette().attention if o.open_spots else None,
                    align_right=True,
                ),
            ],
            empty_message="No shifts on this day.",
            accessible_name="Shifts on the selected day",
        )
        self.info = ShiftInfoPanel(ctx)
        self.info.changed.connect(self.reload)
        self.day_table.selection_changed.connect(self.info.show_shift)
        left_column.addWidget(self.day_table, 1)
        splitter.addWidget(left)
        splitter.addWidget(self.info)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        self.layout_.addWidget(splitter, 1)

    def refresh(self) -> None:
        first = date(self.calendar.yearShown(), self.calendar.monthShown(), 1)
        after = (first + timedelta(days=32)).replace(day=1)
        self._month_shifts = self.ctx.services.opportunities.schedule(
            self.ctx.session,
            starts_after=datetime.combine(first - timedelta(days=7), time.min),
            starts_before=datetime.combine(after + timedelta(days=7), time.min),
        )
        self.calendar.restyle()
        self.calendar.set_shifts(self._month_shifts, self.ctx.services.clock.now().date())
        self._show_day()

    def _show_day(self) -> None:
        day = from_qdate(self.calendar.selectedDate())
        shifts = [o for o in self._month_shifts if o.shift.starts_at.date() == day]
        self.day_title.setText(f"{day:%A}, {format_date(day)}")
        self.day_table.set_records(shifts, keep_selection=lambda o: o.shift.shift_id)
        if self.day_table.selected() is None:
            self.day_table.select_first()
        self.info.show_shift(self.day_table.selected())

    def apply_options(self, **options: object) -> None:
        day = options.get("day")
        if isinstance(day, date):
            self.calendar.setSelectedDate(to_qdate(day))


class SettingsPage(Page):
    key = "settings"
    title = "Settings"
    icon_name = "settings"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx, scrollable=True)
        self.layout_.addWidget(
            PageHeader("Settings", "Make ServeSync comfortable for you, and keep your organization's details current.")
        )

        # Comfort and accessibility (everyone; saved to *their* account) -------
        access = Panel("Comfort and accessibility")
        access.body.addWidget(
            make_label(
                "Your choices follow your account to any computer. Shortcuts: Ctrl+= and Ctrl+- change text size, "
                "Ctrl+Shift+H turns high contrast on or off.",
                "muted",
                wrap=True,
            )
        )
        access.body.addWidget(make_label("Color theme", "section"))
        themes = QHBoxLayout()
        themes.setSpacing(0)
        self.theme_group = QButtonGroup(self)
        descriptions = {
            Theme.SYSTEM: "Match my computer",
            Theme.LIGHT: "Light",
            Theme.DARK: "Dark (less glare)",
            Theme.HIGH_CONTRAST: "High contrast",
        }
        members = list(Theme)
        for index, theme in enumerate(members):
            button = QPushButton(descriptions[theme])
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setProperty("first", index == 0)
            button.setProperty("last", index == len(members) - 1)
            button.setProperty("theme", theme.value)
            button.setAccessibleName(f"Theme: {descriptions[theme]}")
            self.theme_group.addButton(button, index)
            themes.addWidget(button)
        themes.addStretch(1)
        access.body.addLayout(themes)

        access.body.addWidget(make_label("Text size", "section"))
        size_row = QHBoxLayout()
        self.text_size = QSlider(Qt.Orientation.Horizontal)
        self.text_size.setRange(0, len(TEXT_SIZES) - 1)
        self.text_size.setPageStep(1)
        self.text_size.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.text_size.setAccessibleName("Text size")
        self.size_label = make_label("", "muted")
        size_row.addWidget(self.text_size, 1)
        size_row.addWidget(self.size_label)
        access.body.addLayout(size_row)

        access.body.addWidget(make_label("Reading and motion", "section"))
        self.reduce_motion = QCheckBox("Reduce motion — no sliding, fading, or growing animations")
        self.text_spacing = QCheckBox(
            "Extra letter and word spacing — easier for many readers, including with dyslexia"
        )
        self.simplified = QCheckBox("Simplified layout — hide extra panels so each screen shows only the essentials")
        for box in (self.reduce_motion, self.text_spacing, self.simplified):
            access.body.addWidget(box)

        timing_row = QHBoxLayout()
        timing_label = make_label("Keep confirmation messages on screen", None)
        self.message_duration: EnumComboBox[MessageDuration] = EnumComboBox(
            MessageDuration,
            label=lambda m: {
                MessageDuration.STANDARD: "for 6 seconds",
                MessageDuration.LONG: "for 20 seconds",
                MessageDuration.UNTIL_CLOSED: "until I close them",
            }[m],
        )
        self.message_duration.setAccessibleName("Keep confirmation messages on screen")
        timing_label.setBuddy(self.message_duration)
        timing_row.addWidget(timing_label)
        timing_row.addWidget(self.message_duration)
        timing_row.addStretch(1)
        access.body.addLayout(timing_row)

        buttons = QHBoxLayout()
        buttons.addWidget(make_button("Save comfort settings", kind="primary", on_click=self._apply_display))
        buttons.addWidget(make_button("Restore defaults", on_click=self._restore_defaults))
        buttons.addStretch(1)
        access.body.addLayout(buttons)
        self.text_size.valueChanged.connect(lambda value: self.size_label.setText(f"{TEXT_SIZES[value]:.0%}"))
        self.layout_.addWidget(access)

        # Organization (administrators) ----------------------------------------
        self._admin = ctx.session.can(Permission.MANAGE_SETTINGS)
        org = Panel("Organization")
        form = QFormLayout()
        self.org_name = QLineEdit()
        self.org_name.setMaxLength(80)
        self.mission = QPlainTextEdit()
        self.mission.setFixedHeight(80)
        self.hour_value = QDoubleSpinBox()
        self.hour_value.setRange(0.01, 500)
        self.hour_value.setPrefix("$")
        self.hour_value.setDecimals(2)
        self.org_errors = make_label("", "error", wrap=True)
        self.org_errors.hide()
        for label, widget in (
            ("Name", self.org_name),
            ("Mission statement", self.mission),
            ("Value of one volunteer hour", self.hour_value),
        ):
            widget.setAccessibleName(label)
            widget.setEnabled(self._admin)
            form.addRow(label, widget)
        org.body.addLayout(form)
        org.body.addWidget(
            make_label(
                "The value of a volunteer hour turns hours into dollars on the dashboard and in reports. "
                "Independent Sector's national estimate (April 2026) is $36.14; many states publish their own.",
                "hint",
                wrap=True,
            )
        )
        org.body.addWidget(self.org_errors)
        if self._admin:
            org.body.addWidget(
                make_button("Save organization details", kind="primary", on_click=self._save_org),
                0,
                Qt.AlignmentFlag.AlignLeft,
            )
        else:
            org.body.addWidget(make_label("Only administrators can change these details.", "muted"))
        self.layout_.addWidget(org)

        # Account ----------------------------------------------------------
        account = Panel("Your account")
        account.body.addWidget(
            make_label(f"Signed in as {ctx.session.username} ({ctx.session.role.label}).", wrap=True)
        )
        account.body.addWidget(
            make_button("Change password", on_click=self._change_password), 0, Qt.AlignmentFlag.AlignLeft
        )
        self.layout_.addWidget(account)

        if ctx.session.can(Permission.MANAGE_SETTINGS) and not ctx.services.store.db.is_in_memory:
            data = Panel("Data and backup")
            folder = Path(ctx.services.store.db.path).parent
            data.body.addWidget(
                make_label(
                    "Everything ServeSync stores — records, photos, and settings — lives in this folder on this "
                    "computer. To back up, close ServeSync and copy the folder to a USB drive or cloud storage.",
                    "muted",
                    wrap=True,
                )
            )
            data.body.addWidget(make_label(str(folder), None, wrap=True, selectable=True))
            self.layout_.addWidget(data)
        self.layout_.addStretch(1)

    def refresh(self) -> None:
        settings = self.ctx.services.settings
        self._show_appearance(settings.appearance(self.ctx.session))
        self.org_name.setText(settings.organization_name())
        self.mission.setPlainText(settings.mission_statement())
        self.hour_value.setValue(settings.volunteer_hour_value())

    def _show_appearance(self, appearance: Appearance) -> None:
        for button in self.theme_group.buttons():
            button.setChecked(button.property("theme") == appearance.theme.value)
        closest = min(range(len(TEXT_SIZES)), key=lambda i: abs(TEXT_SIZES[i] - appearance.font_scale))
        self.text_size.setValue(closest)
        self.size_label.setText(f"{TEXT_SIZES[closest]:.0%}")
        self.reduce_motion.setChecked(appearance.reduce_motion)
        self.text_spacing.setChecked(appearance.text_spacing)
        self.simplified.setChecked(appearance.simplified)
        self.message_duration.set_value(appearance.message_duration)

    @guarded
    def _apply_display(self) -> None:
        checked = self.theme_group.checkedButton()
        theme = Theme(checked.property("theme")) if checked else Theme.SYSTEM
        self.ctx.services.settings.set_appearance(
            self.ctx.session,
            theme=theme,
            font_scale=TEXT_SIZES[self.text_size.value()],
            reduce_motion=self.reduce_motion.isChecked(),
            text_spacing=self.text_spacing.isChecked(),
            simplified=self.simplified.isChecked(),
            message_duration=self.message_duration.value() or MessageDuration.STANDARD,
        )
        self.ctx.events.appearance_changed.emit()
        self.ctx.events.status_message.emit("Comfort settings saved.")

    @guarded
    def _restore_defaults(self) -> None:
        self._show_appearance(Appearance())
        self._apply_display()

    @guarded
    def _save_org(self) -> None:
        from servesync.core.errors import ValidationError

        self.org_errors.hide()
        try:
            self.ctx.services.settings.update_organization(
                self.ctx.session,
                name=self.org_name.text(),
                hour_value=self.hour_value.value(),
                mission=self.mission.toPlainText(),
            )
        except ValidationError as error:
            self.org_errors.setText("\n".join(error.errors.values()))
            self.org_errors.show()
            return
        self.ctx.changed("Organization details saved.")

    @guarded
    def _change_password(self) -> None:
        if ChangePasswordDialog(self.ctx.services, self.ctx.session, self).exec():
            self.ctx.events.status_message.emit("Password changed.")
