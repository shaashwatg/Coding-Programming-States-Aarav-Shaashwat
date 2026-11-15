"""The topic map, page help (the "?" button), and the first-run tour."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, time

import pytest
from PySide6.QtWidgets import QApplication

from servesync.core.i18n import Language, set_language
from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import Appearance, Theme
from servesync.services import FixedClock, Services
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.help_dialog import PageHelpDialog
from servesync.ui.help_topics import LEADER_TOUR, PAGE_HELP, TOPIC_ROWS, VOLUNTEER_TOUR, page_help_html, topic_html
from servesync.ui.main_window import MainWindow
from tests.factories import FAST_ITERATIONS

pytestmark = pytest.mark.usefixtures("qapp")
SEED_DAY = date(2026, 10, 26)


@pytest.fixture
def demo(store: DataStore, qapp: QApplication) -> Iterator[Services]:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    services = Services.create(
        store, clock=FixedClock(datetime.combine(SEED_DAY, time(8))), password_iterations=FAST_ITERATIONS
    )
    theme.set_font_families(*assets.load_fonts())
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT))
    yield services


def _window(services: Services, username: str, *, offer_tour: bool = False) -> MainWindow:
    return MainWindow(
        AppContext(services, services.auth.sign_in(username, DEMO_PASSWORD), AppEvents()), offer_tour=offer_tour
    )


def test_the_topic_map_covers_every_phrase_of_the_prompt() -> None:
    phrases = " ".join(row.phrase for row in TOPIC_ROWS).casefold()
    for word in (
        "recruit",
        "organize",
        "manage",
        "coordinate",
        "service opportunities",
        "records",
        "participation",
        "volunteers",
        "leaders",
    ):
        assert word in phrases
    assert "How ServeSync addresses the topic" in topic_html()
    set_language(Language.SPANISH)
    assert "Cómo responde ServeSync al tema" in topic_html()


@pytest.mark.parametrize("username", ["coordinator", "priya.patel"])
def test_every_page_has_its_own_help(demo: Services, username: str, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, username)
    qtbot.addWidget(window)
    for key in window.pages:
        assert key in PAGE_HELP, key
        dialog = PageHelpDialog(key, window.ctx.session.role, window)
        qtbot.addWidget(dialog)
        assert "<li>" in dialog.browser.toHtml() or "<li" in dialog.browser.toHtml()
    assert "F1" in page_help_html("no-such-page")


@pytest.mark.parametrize(("username", "tour"), [("coordinator", LEADER_TOUR), ("priya.patel", VOLUNTEER_TOUR)])
def test_the_tour_walks_each_role_through_real_pages(demo: Services, username: str, tour, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, username)
    qtbot.addWidget(window)
    window.resize(1360, 860)
    window.show()
    assert all(step.page in window.pages for step in tour)
    window.start_tour()
    guide = window._tour
    assert guide is not None and guide.counter.text() == f"Step 1 of {len(tour)}"
    for index, step in enumerate(tour):
        assert window.stack.currentWidget() is window.pages[step.page]
        assert window._tour_target(step) is not None
        if index < len(tour) - 1:
            guide.next_button.click()
    assert guide.next_button.text() == "Finish"
    guide.next_button.click()
    assert window._tour is None and demo.settings.tour_seen(window.ctx.session)


def test_the_tour_is_offered_once_and_can_be_skipped(demo: Services, qtbot) -> None:  # type: ignore[no-untyped-def]
    window = _window(demo, "priya.patel", offer_tour=True)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window._tour is not None, timeout=2000)
    assert window._tour is not None
    window._tour.skip_button.click()
    assert window._tour is None
    again = _window(demo, "priya.patel", offer_tour=True)
    qtbot.addWidget(again)
    qtbot.wait(600)
    assert again._tour is None  # seen, so not offered again; Help > Take the tour still replays it
    again.start_tour()
    assert again._tour is not None
