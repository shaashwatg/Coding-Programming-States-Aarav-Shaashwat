"""
Pages used by every role: the shift calendar and settings.

The calendar is the app's "event calendar": a month view marked with dots
(amber when a day still has open spots), with that day's shifts beside it.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
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

from servesync.core.i18n import Language, current_language, format_clock, format_long_day, mark, tr
from servesync.models import Appearance, MessageDuration, ShiftOverview, Theme
from servesync.services import Permission
from servesync.ui.context import AppContext
from servesync.ui.dialogs.auth_dialogs import ChangePasswordDialog, language_switch
from servesync.ui.dialogs.coordination_dialogs import ask_save_path
from servesync.ui.dialogs.data_dialogs import HistoryDialog, PrivacyRequestsPanel
from servesync.ui.pages.base import Page
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import (
    BusyCursor,
    EnumComboBox,
    PageHeader,
    Panel,
    confirm,
    from_qdate,
    guarded,
    inform,
    make_button,
    make_label,
    to_qdate,
)
from servesync.ui.widgets.shift_panel import ShiftInfoPanel, scrollable
from servesync.ui.widgets.table import Column, RecordTable
from servesync.ui.widgets.visuals import ShiftCalendar

TEXT_SIZES = (0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)


def _clock(moment: datetime) -> str:
    return format_clock(moment)


class CalendarPage(Page):
    key = "calendar"
    title = mark("Calendar")
    icon_name = "calendar-days"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self._month_shifts: list[ShiftOverview] = []
        leader = ctx.session.can(Permission.MANAGE_SCHEDULE)
        self.layout_.addWidget(
            PageHeader(
                tr("Calendar"),
                tr("Dots mark days with shifts; amber dots still have open spots. Pick a day to see its shifts.")
                if leader
                else tr("Dots mark days with open shifts. Pick a day, then a shift, to see details and sign up."),
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
                    tr("Time"),
                    lambda o: f"{_clock(o.shift.starts_at)} – {_clock(o.shift.ends_at)}",
                    sort=lambda o: o.shift.starts_at,
                ),
                Column(tr("Program"), lambda o: o.opportunity_title, stretch=True),
                Column(
                    tr("Spots open"),
                    lambda o: o.open_spots,
                    color=lambda o: current_palette().success if o.open_spots else None,  # open spots: emerald
                    align_right=True,
                ),
            ],
            empty_message=tr("No shifts on this day."),
            accessible_name=tr("Shifts on the selected day"),
        )
        self.info = ShiftInfoPanel(ctx)
        self.info.changed.connect(self.reload)
        self.day_table.selection_changed.connect(self.info.show_shift)
        left_column.addWidget(self.day_table, 1)
        splitter.addWidget(left)
        splitter.addWidget(scrollable(self.info))
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
        self.day_title.setText(format_long_day(day))
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
    title = mark("Settings")
    icon_name = "settings"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx, scrollable=True)
        self.layout_.addWidget(
            PageHeader(
                tr("Settings"),
                tr("Make ServeSync comfortable for you, and keep your organization's details current."),
            )
        )

        # Comfort and accessibility (everyone; saved to *their* account) -------
        access = Panel(tr("Comfort and accessibility"))
        access.body.addWidget(
            make_label(
                tr(
                    "Your choices follow your account to any computer. Shortcuts: Ctrl+= "
                    "and Ctrl+- change text size, Ctrl+Shift+H turns high contrast on or "
                    "off."
                ),
                "muted",
                wrap=True,
            )
        )
        # Bilingual on purpose: someone who can't read the current language can still find theirs.
        access.body.addWidget(make_label("Language / Idioma", "section"))
        language_row = QHBoxLayout()
        language_row.addWidget(language_switch(self._choose_language))
        language_row.addStretch(1)
        access.body.addLayout(language_row)

        access.body.addWidget(make_label(tr("Color theme"), "section"))
        themes = QHBoxLayout()
        themes.setSpacing(0)
        self.theme_group = QButtonGroup(self)
        descriptions = {
            Theme.SYSTEM: tr("Match my computer"),
            Theme.LIGHT: tr("Light"),
            Theme.DARK: tr("Dark (less glare)"),
            Theme.HIGH_CONTRAST: tr("High contrast"),
        }
        members = list(Theme)
        for index, theme in enumerate(members):
            button = QPushButton(descriptions[theme])
            button.setCheckable(True)
            button.setProperty("segment", True)
            button.setProperty("first", index == 0)
            button.setProperty("last", index == len(members) - 1)
            button.setProperty("theme", theme.value)
            button.setAccessibleName(tr("Theme: {item}", item=descriptions[theme]))
            self.theme_group.addButton(button, index)
            themes.addWidget(button)
        themes.addStretch(1)
        access.body.addLayout(themes)

        access.body.addWidget(make_label(tr("Text size"), "section"))
        size_row = QHBoxLayout()
        self.text_size = QSlider(Qt.Orientation.Horizontal)
        self.text_size.setRange(0, len(TEXT_SIZES) - 1)
        self.text_size.setPageStep(1)
        self.text_size.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.text_size.setAccessibleName(tr("Text size"))
        self.size_label = make_label("", "muted")
        size_row.addWidget(self.text_size, 1)
        size_row.addWidget(self.size_label)
        access.body.addLayout(size_row)

        access.body.addWidget(make_label(tr("Reading and motion"), "section"))
        self.reduce_motion = QCheckBox(tr("Reduce motion (no sliding, fading, or growing animations)"))
        self.text_spacing = QCheckBox(
            tr("Extra letter and word spacing (easier for many readers, including people with dyslexia)")
        )
        self.legible_font = QCheckBox(
            tr("Easier-to-read letters (a font whose look-alike letters, like I, l and 1, are easy to tell apart)")
        )
        self.simplified = QCheckBox(
            tr("Simplified layout (hide extra panels so each screen shows only the essentials)")
        )
        for box in (self.reduce_motion, self.text_spacing, self.legible_font, self.simplified):
            access.body.addWidget(box)

        timing_row = QHBoxLayout()
        timing_label = make_label(tr("Keep confirmation messages on screen"), None)
        self.message_duration: EnumComboBox[MessageDuration] = EnumComboBox(
            MessageDuration,
            label=lambda m: {
                MessageDuration.STANDARD: tr("for 6 seconds"),
                MessageDuration.LONG: tr("for 20 seconds"),
                MessageDuration.UNTIL_CLOSED: tr("until I close them"),
            }[m],
        )
        self.message_duration.setAccessibleName(tr("Keep confirmation messages on screen"))
        timing_label.setBuddy(self.message_duration)
        timing_row.addWidget(timing_label)
        timing_row.addWidget(self.message_duration)
        timing_row.addStretch(1)
        access.body.addLayout(timing_row)

        buttons = QHBoxLayout()
        buttons.addWidget(make_button(tr("Save comfort settings"), kind="secondary", on_click=self._apply_display))
        buttons.addWidget(make_button(tr("Restore defaults"), on_click=self._restore_defaults))
        buttons.addStretch(1)
        access.body.addLayout(buttons)
        self.text_size.valueChanged.connect(lambda value: self.size_label.setText(f"{TEXT_SIZES[value]:.0%}"))
        self.layout_.addWidget(access)

        # Organization (administrators) ----------------------------------------
        self._admin = ctx.session.can(Permission.MANAGE_SETTINGS)
        org = Panel(tr("Organization"))
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
            (tr("Name"), self.org_name),
            (tr("Mission statement"), self.mission),
            (tr("Value of one volunteer hour"), self.hour_value),
        ):
            widget.setAccessibleName(label)
            widget.setEnabled(self._admin)
            form.addRow(label, widget)
        org.body.addLayout(form)
        org.body.addWidget(
            make_label(
                tr(
                    "The value of a volunteer hour turns hours into dollars on the "
                    "dashboard and in reports. Independent Sector's national estimate "
                    "(April 2026) is $36.14; many states publish their own."
                ),
                "hint",
                wrap=True,
            )
        )
        org.body.addWidget(self.org_errors)
        if self._admin:
            org.body.addWidget(
                make_button(tr("Save organization details"), kind="secondary", on_click=self._save_org),
                0,
                Qt.AlignmentFlag.AlignLeft,
            )
        else:
            org.body.addWidget(make_label(tr("Only administrators can change these details."), "muted"))
        self.layout_.addWidget(org)

        # Account ----------------------------------------------------------
        account = Panel(tr("Your account"))
        account.body.addWidget(
            make_label(
                tr("Signed in as {username} ({label}).", username=ctx.session.username, label=ctx.session.role.label),
                wrap=True,
            )
        )
        account.body.addWidget(
            make_button(tr("Change password"), on_click=self._change_password), 0, Qt.AlignmentFlag.AlignLeft
        )
        self.layout_.addWidget(account)

        self.privacy: PrivacyRequestsPanel | None = None
        if ctx.session.can(Permission.MANAGE_SETTINGS):
            data = Panel(tr("Data and backup"))
            data.body.addWidget(
                make_label(
                    tr(
                        "Save a backup to a USB drive or cloud folder now and then. It holds every record, "
                        "photo and setting in one file. Restoring replaces everything with the backup."
                    ),
                    "muted",
                    wrap=True,
                )
            )
            if not ctx.services.store.db.is_in_memory:
                folder = Path(ctx.services.store.db.path).parent
                data.body.addWidget(
                    make_label(tr("Data folder: {folder}", folder=str(folder)), "hint", wrap=True, selectable=True)
                )
            buttons = QHBoxLayout()
            buttons.addWidget(make_button(tr("Back up…"), on_click=self._backup))
            buttons.addWidget(make_button(tr("Restore…"), kind="danger", on_click=self._restore))
            buttons.addWidget(make_button(tr("Change history…"), on_click=self._history))
            buttons.addStretch(1)
            data.body.addLayout(buttons)
            self.layout_.addWidget(data)
            self.privacy = PrivacyRequestsPanel(ctx)
            self.layout_.addWidget(self.privacy)
        self.layout_.addStretch(1)

    def refresh(self) -> None:
        if self.privacy is not None:
            self.privacy.refresh()
        settings = self.ctx.services.settings
        self._show_appearance(settings.appearance(self.ctx.session))
        self.org_name.setText(settings.organization_name())
        self.mission.setPlainText(settings.mission_statement())
        self.hour_value.setValue(settings.volunteer_hour_value())

    @guarded
    def _backup(self) -> None:
        name = f"servesync-backup-{self.ctx.services.clock.now():%Y-%m-%d}.zip"
        path = ask_save_path(self, name, tr("ServeSync backup"), "zip")
        if path is not None:
            with BusyCursor():
                self.ctx.services.data.backup(self.ctx.session, path)
            self.ctx.changed(
                tr("Backup saved as {name}. Keep a copy somewhere other than this computer.", name=path.name)
            )

    @guarded
    def _restore(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, tr("Choose a ServeSync backup"), str(Path.home()), f"{tr('ServeSync backup')} (*.zip)"
        )
        if not chosen or not confirm(
            self,
            tr("Restore a backup"),
            tr(
                "Replace everything in ServeSync with this backup? Changes made since it was saved will be lost. "
                "Everyone is signed out afterward."
            ),
            tr("Restore"),
        ):
            return
        with BusyCursor():
            manifest = self.ctx.services.data.restore(self.ctx.session, Path(chosen))
        inform(
            self,
            tr("Backup restored"),
            tr("Restored the backup from {when}. Please sign in again.", when=manifest.get("created_at", "")),
        )
        window = self.window()
        sign_out = getattr(window, "sign_out", None)
        if callable(sign_out):
            sign_out()

    @guarded
    def _history(self) -> None:
        HistoryDialog(self.ctx, self).exec()

    def _show_appearance(self, appearance: Appearance) -> None:
        for button in self.theme_group.buttons():
            button.setChecked(button.property("theme") == appearance.theme.value)
        closest = min(range(len(TEXT_SIZES)), key=lambda i: abs(TEXT_SIZES[i] - appearance.font_scale))
        self.text_size.setValue(closest)
        self.size_label.setText(f"{TEXT_SIZES[closest]:.0%}")
        self.reduce_motion.setChecked(appearance.reduce_motion)
        self.text_spacing.setChecked(appearance.text_spacing)
        self.legible_font.setChecked(appearance.legible_font)
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
            legible_font=self.legible_font.isChecked(),
            simplified=self.simplified.isChecked(),
            message_duration=self.message_duration.value() or MessageDuration.STANDARD,
        )
        self.ctx.events.appearance_changed.emit()
        self.ctx.events.status_message.emit(tr("Comfort settings saved."))

    @guarded
    def _choose_language(self, language: Language) -> None:
        """Takes effect right away (the window redraws in the new language)."""
        if language is current_language():
            return
        self.ctx.services.settings.set_appearance(self.ctx.session, language=language)
        self.ctx.events.appearance_changed.emit()

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
        self.ctx.changed(tr("Organization details saved."))

    @guarded
    def _change_password(self) -> None:
        if ChangePasswordDialog(self.ctx.services, self.ctx.session, self).exec():
            self.ctx.events.status_message.emit(tr("Password changed."))
