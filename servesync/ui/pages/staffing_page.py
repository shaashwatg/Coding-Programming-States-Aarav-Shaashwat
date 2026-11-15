"""
Staffing Studio: look ahead, then act (leaders only).

Top to bottom, in the order a coordinator works:
1. Four headline figures
2. Autopilot: a drafted schedule to review, tick, and approve (with Undo)
3. Attendance forecast: which shifts may come up short even when they look full
4. Re-engagement: experienced volunteers who have stopped coming

The logic lives in ``StaffingService``; this page only shows it and sends back
what the coordinator approved. Outlooks always use words as well as color.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem

from servesync.core.i18n import mark, tr, tr_n
from servesync.models import Certification, Volunteer
from servesync.services import DriftAlert, PlanProposal, ShiftForecast, StaffingPlan, TurnoutOutlook
from servesync.ui.context import AppContext
from servesync.ui.dialogs.shift_detail import open_shift
from servesync.ui.pages.base import Page
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import (
    ImpactStrip,
    PageHeader,
    Panel,
    format_date,
    format_hours,
    format_when,
    guarded,
    make_button,
    make_label,
)
from servesync.ui.widgets.table import Column, RecordTable

PROPOSAL_ROLE = int(Qt.ItemDataRole.UserRole)
#: Shows two lines per proposal without pushing the forecast off the screen.
PLAN_LIST_HEIGHT = 300
TABLE_HEIGHT = 300
DRIFT_TABLE_HEIGHT = 190


def _outlook_color(forecast: ShiftForecast) -> str:
    palette = current_palette()
    return {
        TurnoutOutlook.ON_TRACK: palette.success,
        TurnoutOutlook.WATCH: palette.attention,
        TurnoutOutlook.AT_RISK: palette.danger,
    }[forecast.outlook]


class StaffingPage(Page):
    key = "staffing"
    title = mark("Staffing Studio")
    icon_name = "target"

    def __init__(self, ctx: AppContext) -> None:
        super().__init__(ctx, scrollable=True)
        self._plan = StaffingPlan((), 0)
        self._last_approved: tuple[int, ...] = ()
        self.layout_.addWidget(
            PageHeader(
                tr("Staffing Studio"),
                tr("See problems coming in the next two weeks, and fix them in a few clicks."),
            )
        )
        self.strip = ImpactStrip(4)
        self.layout_.addWidget(self.strip)
        self._build_autopilot()
        self._build_forecast()
        self._build_reengagement()
        self._build_certifications()
        self.layout_.addStretch(1)

    # ------------------------------------------------------------------ layout

    def _build_autopilot(self) -> None:
        panel = Panel(tr("Autopilot"))
        panel.body.addWidget(
            make_label(
                tr(
                    "A draft schedule for every open spot. The hardest shifts choose first and work is shared "
                    "fairly. Nobody is signed up until you approve, so untick anyone you'd rather not ask."
                ),
                "muted",
                wrap=True,
            )
        )
        self.plan_list = QListWidget()
        self.plan_list.setAccessibleName(tr("Drafted sign-ups. Press Space to tick or untick one."))
        self.plan_list.setMinimumHeight(PLAN_LIST_HEIGHT)
        self.plan_list.itemChanged.connect(lambda _item: self._update_approve_button())
        panel.body.addWidget(self.plan_list)
        self.plan_summary = make_label("", "hint", wrap=True)
        panel.body.addWidget(self.plan_summary)

        actions = QHBoxLayout()
        self.approve_button = make_button(tr("Sign up selected"), kind="secondary", on_click=self._approve)
        self.undo_button = make_button(tr("Undo last approval"), on_click=self._undo)
        self.undo_button.setEnabled(False)
        actions.addWidget(self.approve_button)
        actions.addWidget(self.undo_button)
        actions.addStretch(1)
        panel.body.addLayout(actions)
        self.layout_.addWidget(panel)

    def _build_forecast(self) -> None:
        panel = Panel(tr("Attendance forecast"))
        panel.body.addWidget(
            make_label(
                tr(
                    "A full roster can still come up short. Expected turnout adds up each person's "
                    "show-up rate, and new volunteers count as 70%."
                ),
                "muted",
                wrap=True,
            )
        )
        self.forecast_table: RecordTable[ShiftForecast] = RecordTable(
            [
                Column(
                    tr("When"),
                    lambda f: format_when(f.overview.shift.starts_at, f.overview.shift.ends_at),
                    sort=lambda f: f.overview.shift.starts_at,
                ),
                Column(tr("Program"), lambda f: f.overview.opportunity_title, stretch=True),
                Column(
                    tr("Signed up"),
                    lambda f: tr(
                        "{filled} of {capacity}", filled=f.overview.filled, capacity=f.overview.shift.capacity
                    ),
                    sort=lambda f: f.overview.fill_ratio,
                    align_right=True,
                ),
                Column(
                    tr("Expected"),
                    lambda f: f"{f.expected_turnout:g}",
                    sort=lambda f: f.expected_turnout,
                    align_right=True,
                ),
                Column(
                    tr("Outlook"),
                    lambda f: f.outlook.label,
                    sort=lambda f: f.expected_turnout / max(f.overview.shift.capacity, 1),
                    color=_outlook_color,
                ),
            ],
            empty_message=tr("No open shifts in the next two weeks."),
            accessible_name=tr("Attendance forecast"),
        )
        self.forecast_table.setMinimumHeight(TABLE_HEIGHT)
        self.forecast_table.activated.connect(self._open_forecast)
        panel.body.addWidget(self.forecast_table)
        panel.body.addWidget(make_label(tr("Double-click a shift to see its best matches."), "hint"))
        self.layout_.addWidget(panel)

    def _build_reengagement(self) -> None:
        panel = Panel(tr("Worth a personal invitation"))
        panel.body.addWidget(
            make_label(
                tr("Experienced volunteers with nothing coming up, and the shift most likely to bring them back."),
                "muted",
                wrap=True,
            )
        )
        self.drift_table: RecordTable[DriftAlert] = RecordTable(
            [
                Column(tr("Volunteer"), lambda a: a.participation.full_name, stretch=True),
                Column(
                    tr("Hours served"),
                    lambda a: format_hours(a.participation.total_hours),
                    sort=lambda a: a.participation.total_hours,
                    align_right=True,
                ),
                Column(
                    tr("Last served"),
                    lambda a: format_date(a.participation.last_served_on) if a.participation.last_served_on else "",
                    sort=lambda a: a.days_away,
                ),
                Column(tr("Invite them to"), _suggestion_text, stretch=True),
            ],
            empty_message=tr("Everyone experienced has served recently or has a shift coming up."),
            accessible_name=tr("Worth a personal invitation"),
            sort_column=1,
            descending=True,
        )
        self.drift_table.setMinimumHeight(DRIFT_TABLE_HEIGHT)
        self.drift_table.activated.connect(self._open_drift)
        panel.body.addWidget(self.drift_table)
        self.layout_.addWidget(panel)

    def _build_certifications(self) -> None:
        panel = Panel(tr("Certifications to renew"))
        panel.body.addWidget(
            make_label(
                tr("Nobody can be scheduled for a program without a current certification, so renew these soon."),
                "muted",
                wrap=True,
            )
        )
        self.certification_table: RecordTable[tuple[Volunteer, Certification]] = RecordTable(
            [
                Column(tr("Volunteer"), lambda pair: pair[0].full_name, stretch=True),
                Column(tr("Certification"), lambda pair: pair[1].name, stretch=True),
                Column(
                    tr("Expiry date"),
                    lambda pair: format_date(pair[1].expires_on),
                    sort=lambda pair: pair[1].expires_on,
                ),
            ],
            empty_message=tr("Every certification is current for at least the next six weeks."),
            accessible_name=tr("Certifications to renew"),
            sort_column=2,
        )
        self.certification_table.setMinimumHeight(DRIFT_TABLE_HEIGHT)
        panel.body.addWidget(self.certification_table)
        self.layout_.addWidget(panel)

    # ------------------------------------------------------------------ data

    def refresh(self) -> None:
        services, session = self.ctx.services, self.ctx.session
        self._plan = services.staffing.draft_plan(session)
        forecasts = services.staffing.forecast(session)
        alerts = services.staffing.drifting_volunteers(session)

        self._show_plan()
        self.forecast_table.set_records(forecasts)
        self.drift_table.set_records(alerts)
        self.certification_table.set_records(services.volunteers.expiring_certifications(session))

        need_attention = sum(1 for f in forecasts if f.outlook is not TurnoutOutlook.ON_TRACK)
        capacity = sum(f.overview.shift.capacity for f in forecasts)
        turnout = sum(f.expected_turnout for f in forecasts) / capacity if capacity else 0.0
        self.strip.set_figures(
            [
                (f"{self._plan.open_spots}", tr("open spots in the next two weeks"), self._plan.open_spots > 0),
                (f"{len(self._plan.proposals)}", tr("spots Autopilot can draft"), False),
                (f"{turnout:.0%}", tr("expected turnout, against capacity"), False),
                (f"{need_attention}", tr("shifts that may come up short"), need_attention > 0),
            ]
        )

    def _show_plan(self) -> None:
        self.plan_list.blockSignals(True)
        self.plan_list.clear()
        for proposal in self._plan.proposals:
            item = QListWidgetItem(_proposal_text(proposal))
            item.setData(PROPOSAL_ROLE, proposal)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.plan_list.addItem(item)
        if not self._plan.proposals:
            empty = QListWidgetItem(tr("Nothing to draft: no open spot has a strong match right now."))
            empty.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.plan_list.addItem(empty)
        self.plan_list.blockSignals(False)
        left_open = self._plan.spots_left_open
        self.plan_summary.setText(
            " ".join(
                part
                for part in (
                    tr_n(
                        "{count} spot has no strong match, so it stays open for you to decide.",
                        "{count} spots have no strong match, so they stay open for you to decide.",
                        left_open,
                    )
                    if left_open
                    else "",
                    tr("Tell each person after you sign them up: ServeSync doesn't send messages."),
                )
                if part
            )
        )
        self._update_approve_button()

    def selected_proposals(self) -> list[PlanProposal]:
        items = (self.plan_list.item(row) for row in range(self.plan_list.count()))
        return [
            item.data(PROPOSAL_ROLE)
            for item in items
            if item.checkState() == Qt.CheckState.Checked and item.data(PROPOSAL_ROLE) is not None
        ]

    def _update_approve_button(self) -> None:
        count = len(self.selected_proposals())
        self.approve_button.setEnabled(count > 0)
        self.approve_button.setText(tr("Sign up {count} selected", count=count) if count else tr("Sign up selected"))

    # ---------------------------------------------------------------- actions

    @guarded
    def _approve(self) -> None:
        result = self.ctx.services.staffing.approve(self.ctx.session, self.selected_proposals())
        self._last_approved = result.assignment_ids
        self.undo_button.setEnabled(bool(result.assignment_ids))
        message = tr_n(
            "Signed up {count} volunteer. Undo is available.",
            "Signed up {count} volunteers. Undo is available.",
            len(result.assignment_ids),
        )
        if result.skipped:
            message += " " + tr(
                "Skipped {count}: {reasons}", count=len(result.skipped), reasons=" ".join(result.skipped)
            )
        self.ctx.changed(message)

    @guarded
    def _undo(self) -> None:
        undone = self.ctx.services.staffing.undo(self.ctx.session, self._last_approved)
        self._last_approved = ()
        self.undo_button.setEnabled(False)
        self.ctx.changed(tr_n("Undid {count} sign-up.", "Undid {count} sign-ups.", undone))

    @guarded
    def _open_forecast(self, forecast: ShiftForecast) -> None:
        open_shift(self.ctx, forecast.overview.shift.shift_id or 0, self, smart_match=True)
        self.reload()

    @guarded
    def _open_drift(self, alert: DriftAlert) -> None:
        if alert.suggestion is not None:
            open_shift(self.ctx, alert.suggestion.overview.shift.shift_id or 0, self, smart_match=True)
            self.reload()


def _proposal_text(proposal: PlanProposal) -> str:
    shift = proposal.overview.shift
    reasons = "; ".join(proposal.match.strengths[:2])
    return tr(
        "{name} ({score}) for {program}, {when}\n{reasons}",
        name=proposal.volunteer.full_name,
        score=proposal.match.score,
        program=proposal.overview.opportunity_title,
        when=format_when(shift.starts_at, shift.ends_at),
        reasons=reasons,
    )


def _suggestion_text(alert: DriftAlert) -> str:
    if alert.suggestion is None:
        return tr("No matching shift right now")
    overview = alert.suggestion.overview
    return f"{overview.opportunity_title}, {format_when(overview.shift.starts_at)}"
