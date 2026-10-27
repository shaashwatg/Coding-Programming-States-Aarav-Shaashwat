"""
Interface tests (pytest-qt). They drive real windows offscreen — clicking
buttons and typing into fields — to prove each screen works end to end.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import Appearance, Theme, VolunteerStatus
from servesync.services import FixedClock, Services
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.auth_dialogs import LoginDialog
from servesync.ui.dialogs.shift_detail import MATCH_TAB, ShiftDetailDialog
from servesync.ui.dialogs.volunteer_dialog import VolunteerDialog
from servesync.ui.main_window import MainWindow
from servesync.ui.widgets.visuals import MatchCard
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


def _window(services: Services, username: str) -> MainWindow:
    session = services.auth.sign_in(username, DEMO_PASSWORD)
    window = MainWindow(AppContext(services, session, AppEvents()))
    window.resize(1360, 860)
    window.show()
    return window


@pytest.fixture(autouse=True)
def _no_blocking_message_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Message boxes would wait for a click; answer them automatically in tests."""
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)


def test_sign_in_dialog_rejects_wrong_password_then_accepts(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = LoginDialog(demo)
    qtbot.addWidget(dialog)
    qtbot.keyClicks(dialog.username, "coordinator")
    qtbot.keyClicks(dialog.password, "wrong-password")
    qtbot.mouseClick(dialog.sign_in_button, Qt.MouseButton.LeftButton)
    assert "incorrect" in dialog.error.text() and dialog.session is None
    assert dialog.password.text() == ""  # cleared for another try

    qtbot.keyClicks(dialog.password, DEMO_PASSWORD)
    qtbot.mouseClick(dialog.sign_in_button, Qt.MouseButton.LeftButton)
    assert dialog.session is not None and dialog.session.username == "coordinator"


def test_leader_window_has_every_page_and_role_specific_call_to_action(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    assert list(window.pages) == ["dashboard", "volunteers", "programs", "calendar", "reports", "settings"]
    assert window.cta.text() == "Add volunteer"
    for key in window.pages:
        window.navigate(key)
        assert window.stack.currentWidget() is window.pages[key]
        assert window.nav_buttons[key].isChecked()


def test_volunteer_window_reaches_find_page_through_call_to_action(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "jordan.rivera")
    qtbot.addWidget(window)
    assert list(window.pages) == ["home", "find", "calendar", "hours", "profile", "settings"]
    assert "find" not in window.nav_buttons and window.cta.text() == "Find a shift"
    qtbot.mouseClick(window.cta, Qt.MouseButton.LeftButton)
    assert window.stack.currentWidget() is window.pages["find"]
    assert not any(button.isChecked() for button in window.nav_buttons.values())


def test_dashboard_shows_live_numbers(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    page = window.pages["dashboard"]
    assert page.header.title.text() == "Riverbend Community Alliance"  # type: ignore[attr-defined]
    assert page.banner.isVisible()  # type: ignore[attr-defined]
    assert page.needs.records()  # type: ignore[attr-defined]
    assert page.feed.count() > 0  # type: ignore[attr-defined]


def test_review_applicants_navigates_with_filter(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    window.ctx.go("volunteers", status="APPLICANT")
    page = window.pages["volunteers"]
    statuses = {v.status for v in page.table.records()}  # type: ignore[attr-defined]
    assert statuses == {VolunteerStatus.APPLICANT}


def test_volunteer_form_shows_errors_beside_fields(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    dialog = VolunteerDialog(window.ctx, None, window)
    qtbot.addWidget(dialog)
    dialog.first_name.setText("J0rdan")
    dialog.email.setText("not-an-email")
    dialog.phone.setText("911-555-0100")
    dialog._on_save()
    errors = {name: label.text() for name, (_widget, label) in dialog._fields.items() if label.text()}
    assert {"first_name", "last_name", "email", "phone"} <= set(errors)
    assert dialog.email.property("invalid") is True
    assert dialog.saved is None and dialog.result() == 0


def test_volunteer_form_saves_valid_person(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    dialog = VolunteerDialog(window.ctx, None, window)
    qtbot.addWidget(dialog)
    dialog.first_name.setText("Morgan")
    dialog.last_name.setText("Lee")
    dialog.email.setText("morgan.lee@example.org")
    dialog.phone.setText("(614) 555-0177")
    dialog._on_save()
    assert dialog.saved is not None and dialog.saved.status is VolunteerStatus.APPLICANT


def test_email_typo_suggestion(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    dialog = VolunteerDialog(window.ctx, None, window)
    qtbot.addWidget(dialog)
    dialog.email.setText("sam@gmial.com")
    dialog._check_email()
    assert "gmail.com" in dialog.suggestion.text()
    dialog._apply_suggestion()
    assert dialog.email.text() == "sam@gmail.com"


def test_smart_match_tab_signs_up_a_recommended_volunteer(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "coordinator")
    qtbot.addWidget(window)
    featured = demo.dashboard.featured_event(window.ctx.session)
    assert featured is not None
    shift_id = featured.overview.shift.shift_id or 0
    dialog = ShiftDetailDialog(window.ctx, shift_id, start_tab=MATCH_TAB, parent=window)
    qtbot.addWidget(dialog)
    cards = dialog.findChildren(MatchCard)
    assert cards, "Smart Match should recommend people for the demo 5K"
    before = demo.store.shifts.count_filled(shift_id)
    sign_up = next(
        button for button in cards[0].findChildren(type(dialog.sign_up_button)) if button.text() == "Sign up"
    )
    qtbot.mouseClick(sign_up, Qt.MouseButton.LeftButton)
    assert demo.store.shifts.count_filled(shift_id) == before + 1


def test_find_page_smart_filter_hides_shifts_volunteer_cannot_join(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "jordan.rivera")
    qtbot.addWidget(window)
    window.navigate("find")
    page = window.pages["find"]
    joinable = page.table.records()  # type: ignore[attr-defined]
    assert joinable and all("Senior Wellness" not in o.opportunity_title for o in joinable)  # 18+ program
    page.can_join.setChecked(False)  # type: ignore[attr-defined]
    assert len(page.table.records()) > len(joinable)  # type: ignore[attr-defined]


def test_theme_and_text_size_apply_live(demo: Services, qtbot, qapp: QApplication) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "jordan.rivera")
    qtbot.addWidget(window)
    window.navigate("settings")
    page = window.pages["settings"]
    page.theme_group.button(3).setChecked(True)  # type: ignore[attr-defined]  # System, Light, Dark, High contrast
    page.text_size.setValue(4)  # type: ignore[attr-defined]
    window.ctx.events.appearance_changed.connect(
        lambda: theme.apply_theme(qapp, demo.settings.appearance().theme, demo.settings.appearance().font_scale)
    )
    page._apply_display()  # type: ignore[attr-defined]
    assert demo.settings.appearance().theme is Theme.HIGH_CONTRAST
    assert theme.current_palette().name == "High contrast"
    assert theme.current_scale() == 1.5
    theme.apply_theme(qapp, Theme.LIGHT, 1.0)


def test_app_starts_signs_in_and_exits_cleanly(tmp_path, monkeypatch: pytest.MonkeyPatch, qapp: QApplication) -> None:  # type: ignore[no-untyped-def]
    """The real start-up path: open the data file, sign in, show the main window."""
    from servesync.ui import app as app_module

    with DataStore.open(tmp_path / "servesync.db") as store:
        seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)

    shown: list[MainWindow] = []

    def fake_login_exec(dialog: LoginDialog) -> int:
        dialog.session = dialog._services.auth.sign_in("coordinator", DEMO_PASSWORD)
        return 1

    monkeypatch.setattr(LoginDialog, "exec", fake_login_exec)
    monkeypatch.setattr(MainWindow, "show", lambda window: shown.append(window))
    monkeypatch.setattr(QApplication, "exec", lambda *_args: 0)
    assert app_module.run([], data_dir=tmp_path) == 0
    assert shown and shown[0].ctx.session.username == "coordinator"
    theme.apply_theme(qapp, Theme.LIGHT, 1.0)


def test_damaged_data_file_shows_message_instead_of_crashing(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    from servesync.ui import app as app_module

    (tmp_path / "servesync.db").write_bytes(b"not a database" * 50)
    messages: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _parent, _title, text: messages.append(text))
    assert app_module.run([], data_dir=tmp_path) == 1
    assert messages and "damaged" in messages[0]
