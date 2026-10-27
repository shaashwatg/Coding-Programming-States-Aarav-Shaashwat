"""
Leader home page: the dashboard.

Laid out for scanning, top to bottom:
1. Mission statement (why we're here)
2. Impact strip (four live numbers)
3. "Happening next" featured event (one spotlight, never a carousel)
4. What needs action this week, plus the live activity feed
5. A calm callout panel at the bottom (no pop-ups)

With **Simplified layout** on, the activity feed and callout are hidden, so
the page shows only what needs action.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QListWidget, QListWidgetItem

from servesync.models import ShiftOverview
from servesync.ui.context import AppContext
from servesync.ui.dialogs.shift_detail import open_shift
from servesync.ui.pages.base import Page
from servesync.ui.theme import current_appearance
from servesync.ui.widgets.common import (
    ImpactStrip,
    PageHeader,
    Panel,
    format_date,
    format_hours,
    format_money,
    format_when,
    guarded,
    make_button,
    make_label,
)
from servesync.ui.widgets.table import Column, RecordTable
from servesync.ui.widgets.visuals import ActivityFeed, Callout, FeaturedBanner


class DashboardPage(Page):
    key = "dashboard"
    title = "Dashboard"
    icon_name = "layout-dashboard"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx, scrollable=True)
        self.header = PageHeader("Dashboard", "")
        self.layout_.addWidget(self.header)
        self.mission = make_label("", "mission", wrap=True)
        self.layout_.addWidget(self.mission)

        self.strip = ImpactStrip(4)
        self.layout_.addWidget(self.strip)

        self.banner = FeaturedBanner()
        self.layout_.addWidget(self.banner)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(18)
        needs = Panel("Shifts that need people this week")
        self.needs: RecordTable[ShiftOverview] = RecordTable(
            [
                Column(
                    "When", lambda o: format_when(o.shift.starts_at, o.shift.ends_at), sort=lambda o: o.shift.starts_at
                ),
                Column("Program", lambda o: o.opportunity_title, stretch=True),
                Column(
                    "Open spots",
                    lambda o: f"{o.open_spots} of {o.shift.capacity}",
                    sort=lambda o: o.open_spots,
                    align_right=True,
                ),
            ],
            empty_message="Every shift this week is full. Nothing to do here.",
            accessible_name="Shifts that need people this week",
        )
        self.needs.setMinimumHeight(260)
        self.needs.activated.connect(lambda overview: self._open(overview, smart=True))
        needs.body.addWidget(self.needs)
        needs.body.addWidget(make_label("Double-click a shift to see its best matches.", "hint"))
        grid.addWidget(needs, 0, 0, 2, 1)

        applicants = Panel("Applicants waiting for review")
        self.applicants = QListWidget()
        self.applicants.setAccessibleName("Applicants waiting for review")
        self.applicants.setMaximumHeight(150)
        applicants.body.addWidget(self.applicants)
        applicants.body.addWidget(
            make_button("Review applicants", on_click=lambda: ctx.go("volunteers", status="APPLICANT")),
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        grid.addWidget(applicants, 0, 1)

        activity = Panel("Recent activity")
        self.activity_panel = activity
        self.feed = ActivityFeed()
        self.feed.setMinimumHeight(220)
        activity.body.addWidget(self.feed)
        grid.addWidget(activity, 1, 1)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        self.layout_.addLayout(grid)

        self.callout = Callout("megaphone")
        self.callout.set_action(make_button("See volunteers", on_click=lambda: ctx.go("volunteers")))
        self.layout_.addWidget(self.callout)
        self.layout_.addStretch(1)

    def refresh(self) -> None:
        services, session = self.ctx.services, self.ctx.session
        simple = current_appearance().simplified
        self.activity_panel.setVisible(not simple)
        self.callout.setVisible(not simple)
        summary = services.dashboard.leader_summary(session)
        now = services.clock.now()
        self.header.set_title(summary.organization_name)
        self.header.instructions.setText(
            f"Today is {now:%A}, {format_date(now.date())}. Here's what needs your attention."
        )
        mission = services.settings.mission_statement()
        self.mission.setText(f"Our mission: {mission}" if mission else "")
        self.mission.setVisible(bool(mission))

        applicants = len(summary.applicants)
        self.strip.set_figures(
            [
                (f"{summary.active_volunteers}", "active volunteers", False),
                (f"{applicants}", "applicants to review", applicants > 0),
                (f"{summary.open_spots}", "open spots in the next 7 days", summary.open_spots > 0),
                (
                    format_hours(summary.hours_this_month),
                    f"served this month, worth {format_money(summary.value_this_month)}",
                    False,
                ),
            ]
        )

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
                    make_button("Find volunteers", kind="primary", on_click=lambda: self._open(overview, smart=True)),
                    make_button("Open roster", on_click=lambda: self._open(overview, smart=False)),
                ]
            )

        self.needs.set_records(list(summary.understaffed))
        self.applicants.clear()
        if not summary.applicants:
            self.applicants.addItem("No one is waiting. New applicants will appear here.")
        for volunteer in summary.applicants:
            item = QListWidgetItem(f"{volunteer.full_name} (applied {format_date(volunteer.joined_on)})")
            self.applicants.addItem(item)
        self.feed.set_items(services.dashboard.activity_feed(session, limit=8), now)

        insight = services.dashboard.recruitment_insight(session)
        if insight is not None:
            self.callout.set_text(
                "Grow your volunteer team",
                f"{insight.top_source.label} brought in {insight.share:.0%} of your {insight.total} volunteers, "
                "more than any other channel. Ask your most reliable volunteers to invite a friend, "
                "and record how each new person heard about you.",
            )

    @guarded
    def _open(self, overview: ShiftOverview, *, smart: bool) -> None:
        open_shift(self.ctx, overview.shift.shift_id or 0, self, smart_match=smart)
        self.reload()
