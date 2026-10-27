"""
Interface tests for reports, Ask ServeSync, charts, feedback, and comfort settings.
They drive real widgets offscreen, the way a person would.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import AccessNeed, Appearance, MessageDuration, Theme
from servesync.services import FixedClock, Services
from servesync.services.reports import ChartSeries, ReportKind, ValueKind
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.assistant_dialog import AssistantDialog
from servesync.ui.dialogs.volunteer_dialog import VolunteerDialog
from servesync.ui.feedback import MAX_TOASTS, Announcer
from servesync.ui.main_window import MainWindow
from servesync.ui.motion import animate, spring_progress
from servesync.ui.pages.reports_page import ReportsPage
from servesync.ui.widgets.charts import ChartView, describe_series
from tests.factories import FAST_ITERATIONS

pytestmark = pytest.mark.usefixtures("qapp")
SEED_DAY = date(2026, 10, 26)


@pytest.fixture
def demo(store: DataStore, qapp: QApplication) -> Iterator[Services]:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    services = Services.create(
        store, clock=FixedClock(datetime.combine(SEED_DAY, time(8, 0))), password_iterations=FAST_ITERATIONS
    )
    theme.set_font_families(*assets.load_fonts())
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT))
    yield services
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT))


@pytest.fixture(autouse=True)
def _no_blocking_message_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)


def _window(services: Services, username: str) -> MainWindow:
    session = services.auth.sign_in(username, DEMO_PASSWORD)
    window = MainWindow(AppContext(services, session, AppEvents()))
    window.resize(1360, 860)
    window.show()
    return window


def _save_to(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))


# ------------------------------------------------------------------ reports


def test_reports_page_shows_figures_insights_charts_and_table(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    window.navigate("reports")
    page = window.pages["reports"]
    assert isinstance(page, ReportsPage) and page.report is not None
    assert page.report.kind is ReportKind.VOLUNTEER_HOURS
    assert page.figures_row.count() == 4 and page.charts and page.table is not None
    assert len(page.table.records()) == len(page.report.rows) > 0
    assert page.insights.isVisible()

    page.kind_box.setCurrentIndex(page.kind_box.findData(ReportKind.PROGRAM_IMPACT.value))
    assert page.report.kind is ReportKind.PROGRAM_IMPACT
    assert page.table.view.model().headerData(0, Qt.Orientation.Horizontal) == "Program"


def test_column_chooser_controls_table_and_export(demo: Services, qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    window.navigate("reports")
    page = window.pages["reports"]
    assert isinstance(page, ReportsPage)
    assert "email" not in page.visible_columns()
    email = next(a for a in page.columns_button.menu().actions() if a.text() == "Email")
    email.setChecked(True)
    assert "email" in page.visible_columns()
    position = [c.key for c in page.report.columns].index("email")  # type: ignore[union-attr]
    assert not page.table.view.isColumnHidden(position)  # type: ignore[union-attr]

    target = tmp_path / "hours.csv"
    _save_to(monkeypatch, target)
    page._export_csv()
    text = target.read_text(encoding="utf-8-sig")
    assert text.splitlines()[0].startswith("Volunteer,") and "Email" in text.splitlines()[0]


def test_pdf_export_writes_a_real_pdf(demo: Services, qtbot, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    window.navigate("reports")
    page = window.pages["reports"]
    assert isinstance(page, ReportsPage)
    target = tmp_path / "report"  # no extension: ".pdf" is added
    _save_to(monkeypatch, target)
    page._export_pdf()
    data = (tmp_path / "report.pdf").read_bytes()
    assert data.startswith(b"%PDF") and len(data) > 5_000


def test_volunteer_sees_only_their_service_record(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "jordan.rivera")
    qtbot.addWidget(window)
    window.navigate("hours")
    page = window.pages["hours"]
    assert isinstance(page, ReportsPage) and page.title == "My hours"
    assert page.kind_box.count() == 1 and page.report is not None
    assert page.report.kind is ReportKind.SERVICE_RECORD
    assert page.report.context[0].startswith("Volunteer: Jordan Rivera")


def test_assistant_can_open_a_specific_report(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    window.ctx.go("reports", kind=ReportKind.RECRUITMENT.value)
    page = window.pages["reports"]
    assert isinstance(page, ReportsPage) and page.report is not None
    assert page.report.kind is ReportKind.RECRUITMENT


# ------------------------------------------------------------ Ask ServeSync


def test_ask_dialog_answers_and_offers_actions(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    dialog = AssistantDialog(window.ctx, window.commands(), window)
    qtbot.addWidget(dialog)
    qtbot.keyClicks(dialog.input, "Who is waiting for approval?")
    qtbot.keyClick(dialog.input, Qt.Key.Key_Return)
    assert dialog.answers and "waiting" in dialog.answers[-1].text
    assert dialog.input.text() == ""  # ready for the next question
    assert dialog.answers[-1].actions[0].page == "volunteers"


def test_ask_dialog_jumps_to_pages(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    dialog = AssistantDialog(window.ctx, window.commands(), window)
    qtbot.addWidget(dialog)
    qtbot.keyClicks(dialog.input, "go to rep")
    assert dialog.matches.count() >= 2  # "Ask: ..." first, then commands
    qtbot.keyClick(dialog.input, Qt.Key.Key_Down)
    assert "Reports" in (dialog.matches.currentItem().text() if dialog.matches.currentItem() else "")
    qtbot.keyClick(dialog.input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.pages["reports"], timeout=2000)


def test_ctrl_k_opens_ask(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "jordan.rivera")
    qtbot.addWidget(window)
    dialog = window.show_assistant()
    qtbot.addWidget(dialog)
    assert dialog.isVisible() and dialog.suggestion_row.count() > 0
    dialog.reject()


# ------------------------------------------------------------------ charts


SERIES = ChartSeries("Hours by program", ("Pantry", "Park", "Library"), (12.0, 4.5, 8.0), ValueKind.HOURS)


def test_charts_are_keyboard_navigable_and_described(qtbot) -> None:  # type: ignore[no-untyped-def]
    chart = ChartView(SERIES)
    qtbot.addWidget(chart)
    spoken: list[str] = []
    chart.item_focused.connect(spoken.append)
    chart.setFocus()
    qtbot.keyClick(chart, Qt.Key.Key_Right)
    qtbot.keyClick(chart, Qt.Key.Key_Right)
    qtbot.keyClick(chart, Qt.Key.Key_End)
    qtbot.keyClick(chart, Qt.Key.Key_Home)
    assert spoken == ["Pantry: 12 h, 1 of 3", "Park: 4.5 h, 2 of 3", "Library: 8 h, 3 of 3", "Pantry: 12 h, 1 of 3"]
    assert "Highest: Pantry" in chart.accessibleDescription() and "Lowest: Park" in chart.accessibleDescription()
    image = chart.render_image(800)
    assert image.width() == 800 and not image.isNull()


def test_empty_chart_says_so() -> None:
    empty = ChartSeries("Hours per week", ("Nov 2",), (0.0,), ValueKind.HOURS, "line")
    assert describe_series(empty) == "Hours per week: no data for this period."


# --------------------------------------------------------- motion & feedback


def test_spring_curve_starts_ends_and_barely_overshoots() -> None:
    samples = [spring_progress(t / 100) for t in range(101)]
    assert samples[0] == 0.0 and samples[-1] == 1.0
    assert max(samples) < 1.03  # lively, not bouncy
    assert samples[10] > 0.2  # responsive start


def test_reduced_motion_jumps_straight_to_the_end(qapp: QApplication, qtbot) -> None:  # type: ignore[no-untyped-def]
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT, reduce_motion=True))
    chart = ChartView()
    qtbot.addWidget(chart)
    assert animate(chart, "progress", 1.0, start=0.0) is None
    assert chart.progress == 1.0
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT))


def test_announcer_coalesces_and_deduplicates(qtbot) -> None:  # type: ignore[no-untyped-def]
    announcer = Announcer()
    spoken: list[str] = []
    announcer.announced.connect(spoken.append)
    announcer.announce("Saved")
    announcer.announce("Saved")
    announcer.announce("3 shifts shown")
    qtbot.waitUntil(lambda: bool(spoken), timeout=1000)
    assert spoken == ["Saved. 3 shifts shown."]
    announcer.announce("Couldn't save", assertive=True)  # errors are spoken immediately
    assert spoken[-1] == "Couldn't save."
    assert len(announcer.history) == 4


def test_toasts_stack_and_respect_message_timing(demo: Services, qtbot, qapp: QApplication) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT, message_duration=MessageDuration.UNTIL_CLOSED))
    for number in range(MAX_TOASTS + 2):
        window.ctx.events.status_message.emit(f"Message {number}")
    assert len(window.toasts.toasts) == MAX_TOASTS
    assert not window.toasts.toasts[-1].is_timed  # waits for the person to close it
    window.toasts.toasts[-1].dismiss()
    assert len(window.toasts.toasts) == MAX_TOASTS - 1
    assert window.announcer.history[-1][1] == f"Message {MAX_TOASTS + 1}"


# --------------------------------------------------------- comfort settings


def test_comfort_settings_save_per_person_and_simplify(demo: Services, qtbot, qapp: QApplication) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    window.ctx.events.appearance_changed.connect(
        lambda: theme.apply_appearance(qapp, demo.settings.appearance(window.ctx.session))
    )
    window.navigate("settings")
    page = window.pages["settings"]
    page.simplified.setChecked(True)  # type: ignore[attr-defined]
    page.reduce_motion.setChecked(True)  # type: ignore[attr-defined]
    page.text_spacing.setChecked(True)  # type: ignore[attr-defined]
    page._apply_display()  # type: ignore[attr-defined]
    saved = demo.settings.appearance(window.ctx.session)
    assert saved.simplified and saved.reduce_motion and saved.text_spacing
    assert QApplication.font().letterSpacing() > 100  # extra spacing applied app-wide
    window.navigate("dashboard")
    dashboard = window.pages["dashboard"]
    assert not dashboard.activity_panel.isVisible() and not dashboard.callout.isVisible()  # type: ignore[attr-defined]


def test_text_size_shortcuts_and_high_contrast_toggle(demo: Services, qtbot, qapp: QApplication) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "jordan.rivera")
    qtbot.addWidget(window)
    window.ctx.events.appearance_changed.connect(
        lambda: theme.apply_appearance(qapp, demo.settings.appearance(window.ctx.session))
    )
    window.change_text_size(1)
    assert theme.current_scale() == 1.15
    window.change_text_size(0)
    assert theme.current_scale() == 1.0
    window.toggle_high_contrast()
    assert theme.current_palette().name == "High contrast"
    window.toggle_high_contrast()
    assert theme.current_palette().name in ("Light", "Dark")  # back to following the computer


# ------------------------------------------------------- inclusive profiles


def test_find_page_respects_access_needs(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "priya.patel")  # relies on public transit
    qtbot.addWidget(window)
    window.navigate("find")
    page = window.pages["find"]
    assert page.fits_access.isVisible() and page.fits_access.isChecked()  # type: ignore[attr-defined]
    fitting = {o.opportunity_title for o in page.table.records()}  # type: ignore[attr-defined]
    assert "Habitat Home Build Day" not in fitting
    page.fits_access.setChecked(False)  # type: ignore[attr-defined]
    everything = {o.opportunity_title for o in page.table.records()}  # type: ignore[attr-defined]
    assert "Habitat Home Build Day" in everything


def test_volunteer_form_saves_name_pronouns_and_needs(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    dialog = VolunteerDialog(window.ctx, None, window)
    qtbot.addWidget(dialog)
    dialog.first_name.setText("Alexandra")
    dialog.last_name.setText("Reyes")
    dialog.preferred_name.setText("Sasha")
    dialog.pronouns.setEditText("they / them")
    dialog.access.boxes[AccessNeed.STEP_FREE].setChecked(True)
    dialog.email.setText("sasha.reyes@example.org")
    dialog.phone.setText("(614) 555-0199")
    dialog._on_save()
    assert dialog.saved is not None
    assert (dialog.saved.full_name, dialog.saved.pronouns) == ("Sasha Reyes", "they/them")
    assert dialog.saved.access_needs == {AccessNeed.STEP_FREE}
