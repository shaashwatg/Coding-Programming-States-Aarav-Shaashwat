"""
The volunteer portal: Home, Find a shift, and My profile.

The home page follows nonprofit layout conventions: mission first, then the
volunteer's own impact, the one event happening next, what's on their
calendar, shifts picked for them, and a friendly callout at the bottom.
With **Simplified layout** on, the callout and score legend are hidden.

Find a shift respects access needs: shifts whose program doesn't list support
for one of the volunteer's needs are hidden by default (one click shows them,
each with a note). Nothing is ever blocked because of an access need.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QGridLayout, QHBoxLayout, QLineEdit, QSplitter, QVBoxLayout, QWidget

from servesync.core.i18n import mark, tr, tr_n
from servesync.models import Announcement, AssignmentStatus, Notice, OpportunityCategory, ServiceRecord, ShiftOverview
from servesync.ui import assets
from servesync.ui.context import AppContext
from servesync.ui.dialogs.auth_dialogs import ChangePasswordDialog
from servesync.ui.dialogs.coordination_dialogs import save_calendar_file
from servesync.ui.dialogs.data_dialogs import MyPrivacyPanel
from servesync.ui.dialogs.goal_dialog import HourGoalPanel
from servesync.ui.dialogs.volunteer_dialog import VolunteerDialog
from servesync.ui.pages.base import Page
from servesync.ui.pages.volunteers_page import VolunteerProfileCard
from servesync.ui.theme import current_appearance
from servesync.ui.widgets.common import (
    EnumComboBox,
    ImpactStrip,
    PageHeader,
    Panel,
    add_search_icon,
    clear_layout,
    confirm,
    format_hours,
    format_money,
    format_when,
    guarded,
    make_button,
    make_label,
)
from servesync.ui.widgets.elements import NEUTRAL, SUCCESS, status_tone
from servesync.ui.widgets.shift_panel import ShiftInfoPanel, scrollable
from servesync.ui.widgets.table import ICON, TAG, Column, RecordTable
from servesync.ui.widgets.visuals import Callout, FactorLegend, FeaturedBanner, MatchCard, UpdatesPanel

#: Icons for the four key figures, in order.
STRIP_ICONS = ["clock", "calendar-check", "badge-check", "hand-heart"]


class HomePage(Page):
    key = "home"
    title = mark("Home")
    icon_name = "house"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx, scrollable=True)
        self.header = PageHeader(tr("Welcome"), tr("Here's what's coming up and where you could help next."))
        self.layout_.addWidget(self.header)
        self.updates = UpdatesPanel()
        self.layout_.addWidget(self.updates)
        self.mission = make_label("", "mission", wrap=True)
        self.layout_.addWidget(self.mission)
        self.strip = ImpactStrip(4, STRIP_ICONS)
        self.layout_.addWidget(self.strip)
        self.goal_panel = HourGoalPanel(ctx)
        self.layout_.addWidget(self.goal_panel)
        self.banner = FeaturedBanner()
        self.layout_.addWidget(self.banner)

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        upcoming = Panel(tr("Your upcoming shifts"), flush=True)
        self.upcoming: RecordTable[ServiceRecord] = RecordTable(
            [
                Column(
                    tr("Program"),
                    lambda r: r.opportunity_title,
                    stretch=True,
                    strong=True,
                    secondary=lambda r: format_when(r.starts_at, r.ends_at),
                    sort=lambda r: r.starts_at,
                ),
            ],
            empty_message=tr("Nothing scheduled yet. Choose Find a shift (top right) to sign up."),
            accessible_name=tr("Your upcoming shifts"),
        )
        self.upcoming.setMinimumHeight(240)
        upcoming.body.addWidget(self.upcoming)
        self.cancel_button = make_button(tr("Cancel sign-up"), on_click=self._cancel)
        self.calendar_button = make_button(tr("Add to calendar"), on_click=self._add_to_calendar, icon="calendar-plus")
        upcoming.add_row(self.calendar_button, self.cancel_button, top=4)
        grid.addWidget(upcoming, 0, 0, Qt.AlignmentFlag.AlignTop)

        picks = Panel(
            tr("Recommended for you"),
            card=False,
            subtitle=tr("Smart Match picks open shifts that fit your availability, skills, and experience."),
        )
        self.legend = FactorLegend()
        picks.body.addWidget(self.legend)
        holder = QWidget()
        self.picks = QVBoxLayout(holder)
        self.picks.setContentsMargins(0, 0, 0, 0)
        self.picks.setSpacing(10)
        picks.body.addWidget(holder)
        grid.addWidget(picks, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.layout_.addLayout(grid)

        self.callout = Callout("hand-heart")
        self.callout.set_text(
            tr("Know someone who'd love to help?"),
            tr(
                "Invite a friend to volunteer with you. When they sign up, ask them to "
                "say you referred them; referrals are how most of our team found us."
            ),
        )
        self.layout_.addWidget(self.callout)
        self.layout_.addStretch(1)

    def refresh(self) -> None:
        services, session = self.ctx.services, self.ctx.session
        volunteer_id = session.volunteer_id or 0
        summary = services.dashboard.volunteer_summary(session, volunteer_id)
        stats = summary.participation
        simple = current_appearance().simplified
        self.callout.setVisible(not simple)
        self.legend.setVisible(not simple)
        self.header.set_title(tr("Welcome back, {given_name}", given_name=summary.volunteer.given_name))
        mission = services.settings.mission_statement()
        self.mission.setText(tr("Our mission: {mission}", mission=mission) if mission else "")
        self.mission.setVisible(bool(mission))
        updates: list[tuple[str, Callable[[], object] | None]] = [
            (describe_notice(notice), partial(self._dismiss, notice.notice_id))
            for notice in services.scheduling.notices(session, volunteer_id)
        ]
        updates += [
            (describe_announcement(note), None)
            for note in services.coordination.my_announcements(session, volunteer_id)
        ]
        self.updates.set_updates(updates)
        reliability = f"{stats.reliability:.0%}" if stats.reliability is not None else tr("New")
        self.strip.set_figures(
            [
                (format_hours(stats.total_hours), tr("hours served"), False),
                (f"{stats.shifts_attended}", tr("shifts completed"), False),
                (reliability, tr("show-up rate"), False),
                (format_money(summary.community_value), tr("value of your time to the community"), False),
            ]
        )

        self.goal_panel.refresh()
        featured = services.dashboard.featured_event(session)
        self.banner.setVisible(featured is not None)
        if featured is not None:
            overview = featured.overview
            self.banner.show_event(
                overview,
                featured.opportunity.description,
                services.opportunities.photo(session, overview.shift.opportunity_id),
            )
            self.banner.set_actions(
                [
                    make_button(
                        tr("See details"),
                        kind="secondary",
                        on_click=lambda: self.ctx.go("calendar", day=overview.shift.starts_at.date()),
                    )
                ]
            )

        self.upcoming.set_records(list(summary.upcoming), keep_selection=lambda r: r.assignment.assignment_id)
        self.cancel_button.setEnabled(bool(summary.upcoming))

        clear_layout(self.picks)
        matches = services.matching.recommend_shifts(session, volunteer_id, limit=3)
        if not matches:
            self.picks.addWidget(
                make_label(
                    tr("No open shifts fit right now. Check Find a shift for everything available."),
                    "muted",
                    wrap=True,
                )
            )
        for match in matches:
            shift = match.overview.shift
            self.picks.addWidget(
                MatchCard(
                    title=match.overview.opportunity_title,
                    subtitle=format_when(shift.starts_at, shift.ends_at),
                    score=match.score,
                    factors=match.factors,
                    action_text=tr("Sign up"),
                    on_action=partial(self._sign_up, shift.shift_id or 0, match.overview.opportunity_title),
                )
            )

    @guarded
    def _sign_up(self, shift_id: int, title: str) -> None:
        self.ctx.services.scheduling.sign_up(self.ctx.session, shift_id, self.ctx.session.volunteer_id or 0)
        self.ctx.changed(tr("You're signed up for {title}. Thank you!", title=title))

    @guarded
    def _add_to_calendar(self) -> None:
        record = self.upcoming.selected() or next(iter(self.upcoming.records()), None)
        if record is not None:
            save_calendar_file(self.ctx, record.assignment.shift_id, self)

    @guarded
    def _dismiss(self, notice_id: int) -> None:
        self.ctx.services.scheduling.dismiss_notice(self.ctx.session, notice_id)
        self.reload()

    @guarded
    def _cancel(self) -> None:
        record = self.upcoming.selected()
        if record is None:
            self.ctx.events.status_message.emit(tr("Select a shift first."))
            return
        if confirm(
            self,
            tr("Cancel sign-up"),
            tr(
                "Cancel your spot at {opportunity_title} on {format_when}?",
                opportunity_title=record.opportunity_title,
                format_when=format_when(record.starts_at),
            ),
            tr("Cancel my spot"),
        ):
            self.ctx.services.scheduling.cancel(self.ctx.session, record.assignment.assignment_id or 0)
            self.ctx.changed(tr("Your sign-up was cancelled. Thanks for letting us know."))


class FindShiftsPage(Page):
    key = "find"
    title = mark("Find a shift")
    icon_name = "search"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self._all: list[ShiftOverview] = []
        self._fit: dict[int, int] = {}
        self._gaps: dict[int, tuple[str, ...]] = {}
        self.layout_.addWidget(
            PageHeader(
                tr("Find a shift"),
                tr(
                    "Browse shifts for the next two months. Fit is your Smart Match score; "
                    "click its header to see your best matches first. Select a shift to "
                    "see details and sign up."
                ),
            )
        )
        filters = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText(tr("Search by program or place"))
        self.search_box.setAccessibleName(tr("Search shifts"))
        self.search_box.setClearButtonEnabled(True)
        add_search_icon(self.search_box)
        self.category: EnumComboBox[OpportunityCategory] = EnumComboBox(
            OpportunityCategory, all_label=tr("All kinds of work")
        )
        self.category.setAccessibleName(tr("Filter by category"))
        self.open_only = QCheckBox(tr("Only shifts with open spots"))
        self.open_only.setChecked(True)
        self.fits_me = QCheckBox(tr("Only times I'm usually free"))
        self.fits_me.setToolTip(tr("Uses the availability on your profile"))
        self.can_join = QCheckBox(tr("Only shifts I can sign up for"))
        self.can_join.setChecked(True)
        self.can_join.setToolTip(tr("Hides shifts you're too young for or that clash with your schedule"))
        self.fits_access = QCheckBox(tr("Only shifts that fit my access needs"))
        self.fits_access.setChecked(True)
        self.fits_access.setToolTip(
            tr("Uses the access needs on your profile. Turn off to see every shift, with notes.")
        )
        self.fits_access.toggled.connect(lambda _c: self._apply_filters())
        for widget in (self.search_box,):
            widget.textChanged.connect(lambda _t: self._apply_filters())
        self.category.currentIndexChanged.connect(lambda _i: self._apply_filters())
        self.open_only.toggled.connect(lambda _c: self._apply_filters())
        self.fits_me.toggled.connect(lambda _c: self._apply_filters())
        self.can_join.toggled.connect(lambda _c: self._apply_filters())
        filters.addWidget(self.search_box, 2)
        filters.addWidget(self.category, 1)
        self.layout_.addLayout(filters)
        # Two columns, so the full wording fits even at large text sizes.
        toggles = QGridLayout()
        toggles.setHorizontalSpacing(24)
        toggles.setVerticalSpacing(0)
        for index, box in enumerate((self.can_join, self.open_only, self.fits_me, self.fits_access)):
            toggles.addWidget(box, index // 2, index % 2)
        toggles.setColumnStretch(2, 1)
        self.layout_.addLayout(toggles)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.table: RecordTable[ShiftOverview] = RecordTable(
            [
                Column(
                    tr("Program"),
                    lambda o: o.opportunity_title,
                    stretch=True,
                    kind=ICON,
                    icon=lambda o: assets.CATEGORY_ICONS[o.category],
                    secondary=lambda o: format_when(o.shift.starts_at, o.shift.ends_at),
                    sort=lambda o: o.shift.starts_at,
                ),
                Column(
                    tr("Spots open"),
                    lambda o: tr("{count} open", count=o.open_spots) if o.open_spots else tr("Full"),
                    sort=lambda o: o.open_spots,
                    kind=TAG,
                    tone=lambda o: SUCCESS if o.open_spots else NEUTRAL,
                ),
                Column(
                    tr("Fit"),
                    lambda o: self._fit.get(o.shift.shift_id or 0, ""),
                    sort=lambda o: self._fit.get(o.shift.shift_id or 0, -1),
                    tooltip=lambda o: tr("Smart Match score out of 100 (click the header to sort by best fit)"),
                    align_right=True,
                ),
                Column(
                    tr("Access"),
                    lambda o: self._access_text(o),
                    tooltip=lambda o: (
                        "; ".join(self._gaps.get(o.shift.shift_id or 0, ())) or tr("Fits your access needs")
                    ),
                ),
            ],
            empty_message=tr("No shifts match these filters. Try turning a filter off."),
            accessible_name=tr("Open shifts"),
        )
        shifts = Panel(card=True, flush=True)
        shifts.body.setContentsMargins(0, 4, 0, 10)
        shifts.body.addWidget(self.table)
        splitter.addWidget(shifts)
        self.info = ShiftInfoPanel(ctx)
        self.info.changed.connect(self.reload)
        self.table.selection_changed.connect(lambda o: self.info.show_shift(o))
        splitter.addWidget(scrollable(self.info))
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([620, 440])
        self.layout_.addWidget(splitter, 1)

    def refresh(self) -> None:
        services, session = self.ctx.services, self.ctx.session
        volunteer_id = session.volunteer_id or 0
        self._all = services.opportunities.upcoming_schedule(session, days=60)
        self._volunteer = services.volunteers.get(session, volunteer_id)
        eligible = services.matching.recommend_shifts(
            session, volunteer_id, limit=1000, diversify=False, only_fitting_access=False
        )
        self._fit = {match.overview.shift.shift_id or 0: match.score for match in eligible}
        self._gaps = {match.overview.shift.shift_id or 0: match.access_gaps for match in eligible if match.access_gaps}
        has_needs = bool(self._volunteer.access_needs)
        self.fits_access.setVisible(has_needs)
        self.table.view.setColumnHidden(4, not has_needs)
        self._apply_filters()

    def _access_text(self, overview: ShiftOverview) -> str:
        if not self._volunteer.access_needs:
            return ""
        gaps = self._gaps.get(overview.shift.shift_id or 0)
        return tr("Check with coordinator") if gaps else tr("Fits your needs")

    def _apply_filters(self) -> None:
        text = (self.search_box.text() if self.search_box else "").strip().casefold()
        category = self.category.value()
        rows = [
            o
            for o in self._all
            if (not text or text in o.opportunity_title.casefold() or text in o.location.casefold())
            and (category is None or o.category is category)
            and (not self.open_only.isChecked() or o.open_spots > 0)
            and (not self.fits_me.isChecked() or self._volunteer.is_available_at(o.shift.starts_at))
            and (not self.can_join.isChecked() or (o.shift.shift_id or 0) in self._fit)
            and (
                not self.fits_access.isChecked()
                or not self._volunteer.access_needs
                or (o.shift.shift_id or 0) not in self._gaps
            )
        ]
        self.table.set_records(rows, keep_selection=lambda o: o.shift.shift_id)
        if self.table.selected() is None:
            self.table.select_first()
        self.info.show_shift(self.table.selected())
        self.ctx.announce(tr_n("{count} shift shown", "{count} shifts shown", len(rows)))


class ProfilePage(Page):
    key = "profile"
    title = mark("My profile")
    icon_name = "user-round"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx)
        self.layout_.addWidget(
            PageHeader(
                tr("My profile"),
                tr(
                    "Keep your contact details and availability current so coordinators "
                    "can reach you and Smart Match can suggest shifts that fit."
                ),
                [
                    make_button(tr("Edit my profile"), kind="secondary", on_click=self._edit),
                    make_button(tr("Change password"), on_click=self._password),
                ],
            )
        )
        row = QHBoxLayout()
        row.setSpacing(16)
        self.card = VolunteerProfileCard(show_notes=False)
        row.addWidget(self.card, 2, Qt.AlignmentFlag.AlignTop)
        history = Panel(tr("My service history"), flush=True)
        self.history: RecordTable[ServiceRecord] = RecordTable(
            [
                Column(
                    tr("Program"),
                    lambda r: r.opportunity_title,
                    stretch=True,
                    strong=True,
                    secondary=lambda r: format_when(r.starts_at, r.ends_at),
                    sort=lambda r: r.starts_at,
                ),
                Column(
                    tr("Status"),
                    lambda r: r.assignment.status.label,
                    kind=TAG,
                    tone=lambda r: status_tone(r.assignment.status),
                ),
                Column(
                    tr("Hours"),
                    lambda r: (
                        format_hours(r.assignment.counted_hours)
                        if r.assignment.status is AssignmentStatus.ATTENDED
                        else ""
                    ),
                    sort=lambda r: r.assignment.counted_hours,
                    align_right=True,
                ),
            ],
            empty_message=tr("Your completed shifts will be listed here."),
            accessible_name=tr("My service history"),
            descending=True,
        )
        history.body.addWidget(self.history, 1)
        row.addWidget(history, 3)
        self.layout_.addLayout(row, 1)
        self.privacy = MyPrivacyPanel(ctx)
        self.layout_.addWidget(self.privacy)

    def refresh(self) -> None:
        services, session = self.ctx.services, self.ctx.session
        volunteer_id = session.volunteer_id or 0
        self.privacy.refresh()
        self.card.show_volunteer(
            services.volunteers.get(session, volunteer_id), services.volunteers.participation(session, volunteer_id)
        )
        self.history.set_records(services.volunteers.history(session, volunteer_id))

    @guarded
    def _edit(self) -> None:
        volunteer = self.ctx.services.volunteers.get(self.ctx.session, self.ctx.session.volunteer_id or 0)
        if VolunteerDialog(self.ctx, volunteer, self).exec():
            self.ctx.changed(tr("Your profile was saved."))

    @guarded
    def _password(self) -> None:
        if ChangePasswordDialog(self.ctx.services, self.ctx.session, self).exec():
            self.ctx.events.status_message.emit(tr("Password changed."))


def describe_notice(notice: Notice) -> str:
    """A notice in the reader's language (stored as a kind and a shift, not as a sentence)."""
    role = tr(" as {role}", role=notice.role_name) if notice.role_name else ""
    return tr(
        "A spot opened on {program}, {when}, and you were next on the waitlist. You're now signed up{role}.",
        program=notice.opportunity_title,
        when=format_when(notice.starts_at, notice.ends_at),
        role=role,
    )


def describe_announcement(note: Announcement) -> str:
    """'Weekend Food Pantry, Sat, Nov 14: Parking is in the north lot.' (the leader's words, unchanged)."""
    if note.shift_starts_at is not None:
        about = tr("{program}, {when}", program=note.opportunity_title, when=format_when(note.shift_starts_at))
    else:
        about = note.opportunity_title
    return tr("{about}: {body} (posted by {who})", about=about, body=note.body, who=note.posted_by)
