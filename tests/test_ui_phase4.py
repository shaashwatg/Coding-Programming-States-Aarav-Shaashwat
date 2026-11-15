"""Interface tests for announcements, tomorrow's reminders, and calendar files, driving real widgets."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, DEMO_SHIFT_ANNOUNCEMENT, seed_demo_data
from servesync.models import Appearance, Theme
from servesync.services import FixedClock, Services
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.coordination_dialogs import AnnounceDialog, RemindersDialog, save_calendar_file
from servesync.ui.pages.volunteer_pages import HomePage
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


def _save_to(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))


def test_reminders_export_a_csv_call_list(demo: Services, qtbot, monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    dialog = RemindersDialog(_ctx(demo, "coordinator"))
    qtbot.addWidget(dialog)
    assert dialog.table.records() and dialog.export_button.isEnabled()
    _save_to(monkeypatch, tmp_path / "calls")
    dialog._export()
    text = (tmp_path / "calls.csv").read_text(encoding="utf-8-sig")
    assert text.startswith("Volunteer,Phone,Email") and len(text.splitlines()) == len(dialog.table.records()) + 1


def test_an_empty_announcement_is_explained_beside_the_box(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    ctx = _ctx(demo, "coordinator")
    program = next(o for o in demo.opportunities.find_all(ctx.session) if o.title == "Community 5K Fun Run")
    dialog = AnnounceDialog(ctx, program.title, opportunity_id=program.opportunity_id)
    qtbot.addWidget(dialog)
    dialog._post()
    assert not dialog.error.isHidden() and dialog.error.text()
    dialog.text.setPlainText("Wear sunscreen.")
    dialog._post()
    notes = demo.coordination.announcements(ctx.session, opportunity_id=program.opportunity_id)
    assert notes[0].body == "Wear sunscreen."


def test_home_shows_announcements_and_saves_a_calendar_file(  # type: ignore[no-untyped-def]
    demo: Services, qtbot, monkeypatch, tmp_path: Path
) -> None:
    ctx = _ctx(demo, "priya.patel")
    page = HomePage(ctx)
    qtbot.addWidget(page)
    page.refresh()
    assert not page.updates.isHidden()
    assert any(DEMO_SHIFT_ANNOUNCEMENT in label.text() for label in page.updates.findChildren(type(page.mission)))
    record = page.upcoming.records()[0]
    _save_to(monkeypatch, tmp_path / "shift.ics")
    save_calendar_file(ctx, record.assignment.shift_id, page)
    assert (tmp_path / "shift.ics").read_text().startswith("BEGIN:VCALENDAR")
