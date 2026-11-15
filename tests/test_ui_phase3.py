"""Interface tests for roles, waitlists, Home notices, and expiring certifications, driving real widgets."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import Appearance, OpportunityStatus, Theme
from servesync.services import FixedClock, Services
from servesync.services.reports import ReportKind
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.roles_dialog import RolesDialog
from servesync.ui.main_window import MainWindow
from servesync.ui.pages.leader_pages import DashboardPage
from servesync.ui.pages.reports_page import ReportsPage
from servesync.ui.pages.volunteer_pages import HomePage
from servesync.ui.widgets.shift_panel import ShiftInfoPanel
from tests.factories import FAST_ITERATIONS

pytestmark = pytest.mark.usefixtures("qapp")
SEED_DAY = date(2026, 10, 26)


@pytest.fixture
def demo(store: DataStore, qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[Services]:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    services = Services.create(
        store, clock=FixedClock(datetime.combine(SEED_DAY, time(8, 0))), password_iterations=FAST_ITERATIONS
    )
    theme.set_font_families(*assets.load_fonts())
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    yield services


def _ctx(services: Services, username: str) -> AppContext:
    return AppContext(services, services.auth.sign_in(username, DEMO_PASSWORD), AppEvents())


def test_leader_edits_roles_and_errors_name_the_role(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx(demo, "coordinator")
    now = demo.clock.now()
    shift = next(
        o
        for o in demo.store.shifts.overviews(starts_after=now, opportunity_status=OpportunityStatus.OPEN)
        if o.filled >= 1 and len(demo.store.shifts.roles(o.shift.shift_id or 0)) == 1
    )
    shift_id = shift.shift.shift_id or 0
    dialog = RolesDialog(ctx, shift_id, demo.scheduling.roles(ctx.session, shift_id))
    qtbot.addWidget(dialog)
    dialog.rows[0].capacity.setValue(1)
    dialog.rows[0].name.setText("Sorting")
    if shift.filled > 1:  # too small for the people already in it: the error names the role
        dialog._save()
        assert not dialog.banner.isHidden() and dialog.banner.text().startswith("Sorting:")
        dialog.rows[0].capacity.setValue(shift.filled)
    dialog._add_row(None, 0)
    dialog.rows[1].name.setText("Greeter")
    dialog.rows[1].capacity.setValue(2)
    dialog._save()
    names = [role.role.name for role in demo.scheduling.roles(ctx.session, shift_id)]
    assert names == ["Sorting", "Greeter"]
    assert demo.store.shifts.get(shift_id).capacity == max(1, shift.filled) + 2


def test_volunteer_can_join_the_waitlist_of_a_full_shift(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx(demo, "priya.patel")
    volunteer_id = ctx.session.volunteer_id or 0
    full = next(
        o
        for o in demo.store.shifts.overviews(starts_after=demo.clock.now(), opportunity_status=OpportunityStatus.OPEN)
        if o.is_full and not demo.scheduling.why_not_waitlist(ctx.session, o.shift.shift_id or 0, volunteer_id)
    )
    panel = ShiftInfoPanel(ctx)
    qtbot.addWidget(panel)
    panel.show_shift(full)
    assert panel.primary.text() == "Join waitlist" and panel.primary.isEnabled()
    panel.primary.click()
    assert demo.scheduling.waitlist_position(ctx.session, full.shift.shift_id or 0, volunteer_id) is not None
    panel.show_shift(demo.store.shifts.get_overview(full.shift.shift_id or 0))
    assert panel.primary.text() == "Leave waitlist"


def test_home_shows_and_dismisses_a_waitlist_notice(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx(demo, "priya.patel")
    page = HomePage(ctx)
    qtbot.addWidget(page)
    page.refresh()
    assert not page.updates.isHidden()
    assert demo.scheduling.notices(ctx.session, ctx.session.volunteer_id or 0)
    notice = demo.scheduling.notices(ctx.session, ctx.session.volunteer_id or 0)[0]
    page._dismiss(notice.notice_id)
    assert demo.scheduling.notices(ctx.session, ctx.session.volunteer_id or 0) == []
    texts = [label.text() for label in page.updates.findChildren(type(page.mission)) if not label.isHidden()]
    assert not any("waitlist" in text for text in texts)  # announcements may remain; the notice is gone


def test_dashboard_lists_expiring_items_and_opens_the_report(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = MainWindow(_ctx(demo, "coordinator"))
    qtbot.addWidget(window)
    page = window.pages["dashboard"]
    assert isinstance(page, DashboardPage)
    page.refresh()
    texts = [page.expiring.item(i).text() for i in range(page.expiring.count())]
    assert texts and any("expires" in text for text in texts)
    window.navigate("reports", kind=ReportKind.CERTIFICATION_EXPIRY.value)
    reports = window.pages["reports"]
    assert isinstance(reports, ReportsPage) and reports.report is not None
    assert reports.report.kind is ReportKind.CERTIFICATION_EXPIRY and reports.report.rows
    assert reports.period_box.isHidden()
