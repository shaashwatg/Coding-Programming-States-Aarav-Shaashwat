"""Interface tests for import, change history, backups, and privacy, driving real widgets."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import Appearance, Theme
from servesync.services import FixedClock, Services
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.data_dialogs import HistoryDialog, ImportDialog, MyPrivacyPanel, PrivacyRequestsPanel
from servesync.ui.pages.shared_pages import SettingsPage
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
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok)
    yield services


def _ctx(services: Services, username: str) -> AppContext:
    return AppContext(services, services.auth.sign_in(username, DEMO_PASSWORD), AppEvents())


def test_import_dialog_blocks_until_every_row_is_fixed(demo: Services, qtbot, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    dialog = ImportDialog(_ctx(demo, "coordinator"))
    qtbot.addWidget(dialog)
    bad = tmp_path / "bad.csv"
    bad.write_text("First name,Last name,Email,Phone,Birth date\nMaria,Gomez,not-an-email,206-555-0170,03/04/1990\n")
    dialog.load(bad)
    assert not dialog.import_button.isEnabled() and "needs fixing" in dialog.summary.text()
    good = tmp_path / "good.csv"
    good.write_text(
        "First name,Last name,Email,Phone,Birth date\nMaria,Gomez,maria@example.org,206-555-0170,03/04/1990\n"
    )
    dialog.load(good)
    assert dialog.import_button.isEnabled()
    dialog.import_button.click()
    assert dialog.imported == 1 and demo.store.volunteers.find_by_email("maria@example.org") is not None


def test_history_lists_changes_in_plain_words_and_filters(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    dialog = HistoryDialog(_ctx(demo, "admin"))
    qtbot.addWidget(dialog)
    entries = dialog.table.records()
    assert entries and any(entry.details == "APPLICANT>ACTIVE" for entry in entries)
    dialog.search.setText("coordinator")
    assert dialog.table.records() and all("coordinator" in e.changed_by for e in dialog.table.records())


def test_settings_backs_up_to_the_chosen_file(demo: Services, qtbot, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    page = SettingsPage(_ctx(demo, "admin"))
    qtbot.addWidget(page)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "copy"), ""))
    page._backup()
    assert (tmp_path / "copy.zip").stat().st_size > 0


def test_an_admin_completes_the_demo_privacy_request(demo: Services, qtbot, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx(demo, "admin")
    panel = PrivacyRequestsPanel(ctx)
    qtbot.addWidget(panel)
    panel.refresh()
    (request,) = demo.data.deletion_requests(ctx.session)
    monkeypatch.setattr("servesync.ui.dialogs.data_dialogs.confirm", lambda *a, **k: True)
    panel._complete(request)
    assert demo.data.deletion_requests(ctx.session) == []


def test_a_volunteer_downloads_their_data_and_asks_for_deletion(  # type: ignore[no-untyped-def]
    demo: Services, qtbot, monkeypatch, tmp_path: Path
) -> None:
    ctx = _ctx(demo, "priya.patel")
    panel = MyPrivacyPanel(ctx)
    qtbot.addWidget(panel)
    panel.refresh()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "mine.json"), ""))
    panel._download()
    assert json.loads((tmp_path / "mine.json").read_text())["profile"]["first_name"] == "Priya"
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *a, **k: ("Moving away", True))
    panel._request()
    assert not panel.request_button.isEnabled() and "will handle it" in panel.status.text()
