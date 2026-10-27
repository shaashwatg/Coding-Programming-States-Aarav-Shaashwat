"""
Spanish translation: the catalog is complete, sentences read correctly, and
the whole app — dates, the assistant, help, and every screen — works in Spanish.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from datetime import date, datetime, time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from servesync.core.i18n import (
    Language,
    catalog,
    current_language,
    format_clock,
    format_day,
    format_long_day,
    format_weekday_day,
    set_language,
    tr,
    tr_n,
    weekday_plural,
)
from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import Appearance, AssignmentStatus, DayPart, Theme, Weekday
from servesync.models.enums import describe_slot
from servesync.services import FixedClock, Services
from servesync.services.assistant.knowledge import ARTICLES, ARTICLES_ES, search_help
from servesync.services.assistant.language import Intent, Slot, classify, find_period, find_slot, normalize
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.help_dialog import HelpDialog
from servesync.ui.main_window import MainWindow
from tests.factories import FAST_ITERATIONS
from tests.test_ui_features import SEED_DAY

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import messages

TODAY = date(2026, 11, 2)  # a Monday


@pytest.fixture
def spanish() -> Iterator[None]:
    set_language(Language.SPANISH)
    yield
    set_language(Language.ENGLISH)


# ------------------------------------------------------------------ catalog


def test_every_message_has_a_spanish_translation() -> None:
    missing = sorted(messages.all_messages() - set(messages.load_catalog()))
    assert not missing, f"Add these to servesync/locale/es.json (python tools/messages.py --missing): {missing[:10]}"


def test_catalog_has_no_leftover_entries() -> None:
    unused = sorted(set(messages.load_catalog()) - messages.all_messages())
    assert not unused, f"These translations are no longer used: {unused[:10]}"


def test_translations_keep_every_placeholder() -> None:
    broken = {
        english: spanish
        for english, spanish in messages.load_catalog().items()
        if messages.placeholders(english) != messages.placeholders(spanish)
    }
    assert not broken


def test_translations_are_real_translations() -> None:
    entries = messages.load_catalog()
    assert all(value.strip() for value in entries.values())
    same_in_both = {"Error: {message}", "Smart Match"}  # genuinely identical in Spanish
    untouched = [k for k, v in entries.items() if k == v and len(k) > 4 and k not in same_in_both]
    assert untouched == []  # copied English would slip through the missing-message check


def test_catalog_is_valid_utf8_json() -> None:
    raw = messages.CATALOG.read_bytes().decode("utf-8")
    assert "¿" in raw and "ñ" in raw
    assert isinstance(json.loads(raw), dict)


def test_no_database_text_is_marked_for_translation() -> None:
    sql_words = (" WHERE ", " ORDER BY ", " LIKE ? ", "SAVEPOINT", "BEGIN ", "SELECT ")
    assert [m for m in messages.all_messages() if any(word in m for word in sql_words)] == []


# ------------------------------------------------------------- tr and tr_n


def test_english_needs_no_catalog_and_fills_fields() -> None:
    assert tr("Saved {title}.", title="Food Pantry") == "Saved Food Pantry."


def test_spanish_translates_and_fills_fields(spanish: None) -> None:
    assert tr("Saved {title}.", title="Food Pantry") == "Se guardó Food Pantry."
    assert tr("Sign out") == "Cerrar sesión"


def test_unknown_message_falls_back_to_english(spanish: None) -> None:
    assert tr("A message nobody translated, {name}", name="Ana") == "A message nobody translated, Ana"


def test_broken_translation_falls_back_to_english(spanish: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(catalog(Language.SPANISH), "Hi {name}", "Hola {nombre}")
    assert tr("Hi {name}", name="Ana") == "Hi Ana"


def test_plurals(spanish: None) -> None:
    assert tr_n("{count} spot open.", "{count} spots open.", 1) == "1 lugar libre."
    assert tr_n("{count} spot open.", "{count} spots open.", 3) == "3 lugares libres."


def test_switching_language_takes_effect_immediately() -> None:
    assert AssignmentStatus.ATTENDED.label == "Attended"
    set_language(Language.SPANISH)
    assert AssignmentStatus.ATTENDED.label == "Asistió"
    assert Theme.HIGH_CONTRAST.label == "Alto contraste"
    set_language(Language.ENGLISH)
    assert AssignmentStatus.ATTENDED.label == "Attended"


# -------------------------------------------------------------------- dates


def test_dates_and_times_in_english() -> None:
    moment = datetime(2026, 11, 7, 14, 30)
    assert format_day(moment.date()) == "Nov 7, 2026"
    assert format_weekday_day(moment.date()) == "Sat, Nov 7"
    assert format_clock(moment) == "2:30 PM"


def test_dates_and_times_in_spanish(spanish: None) -> None:
    moment = datetime(2026, 11, 7, 9, 5)
    assert format_day(moment.date()) == "7 nov 2026"
    assert format_weekday_day(moment.date()) == "sáb 7 nov"
    assert format_long_day(moment.date()) == "sábado, 7 nov 2026"
    assert format_clock(moment) == "9:05 a. m."
    assert format_clock(time(12, 0)) == "12:00 p. m."


def test_weekday_plurals(spanish: None) -> None:
    assert weekday_plural(int(Weekday.SATURDAY)) == "sábados"
    assert weekday_plural(int(Weekday.MONDAY)) == "lunes"  # lunes to viernes don't change
    assert describe_slot(Weekday.SUNDAY, DayPart.EVENING) == "domingos por la noche"


# ------------------------------------------------------------ understanding


def test_accents_are_optional() -> None:
    assert normalize("¿Quién está libre el sábado?") == normalize("quien esta libre el sabado")


@pytest.mark.parametrize(
    ("question", "intent", "leader"),
    [
        ("¿Cuántas horas tengo este mes?", Intent.MY_HOURS, False),
        ("¿Cuándo es mi próximo turno?", Intent.MY_NEXT_SHIFT, False),
        ("¿En qué debería inscribirme?", Intent.RECOMMEND_SHIFTS, False),
        ("¿Quién está libre el sábado por la mañana?", Intent.WHO_IS_FREE, True),
        ("¿Qué turnos necesitan voluntarios esta semana?", Intent.SHIFTS_NEEDING_PEOPLE, True),
        ("¿Quién espera aprobación? solicitantes pendientes", Intent.APPLICANTS, True),
        ("¿Cómo exporto un informe?", Intent.HOW_TO, True),
        ("Hola", Intent.GREETING, True),
        ("¡Gracias!", Intent.THANKS, True),
    ],
)
def test_spanish_questions_reach_the_right_answer(question: str, intent: Intent, leader: bool) -> None:
    parsed = classify(question, today=TODAY, people=[], programs=[], is_leader=leader)
    assert parsed.intent is intent


def test_spanish_time_words() -> None:
    slot = find_slot("¿Quién está libre el sábado por la mañana?")
    assert slot == Slot((Weekday.SATURDAY,), DayPart.MORNING)
    assert find_slot("entre semana por la tarde") == Slot(tuple(d for d in Weekday if d < 5), DayPart.AFTERNOON)
    tomorrow = find_period("¿quién viene mañana?", TODAY)
    assert tomorrow is not None and tomorrow.start == date(2026, 11, 3)
    # "por la mañana" is a time of day, not "tomorrow"
    assert find_period("el sábado por la mañana", TODAY) is None
    october = find_period("horas en octubre", TODAY)
    assert october is not None and october.start == date(2026, 10, 1)


def test_period_and_slot_labels_follow_the_language(spanish: None) -> None:
    period = find_period("this month", TODAY)
    assert period is not None and period.label == "este mes"
    october = find_period("en octubre", TODAY)
    assert october is not None and october.label == "en octubre de 2026"
    assert Slot((Weekday.SATURDAY,), DayPart.MORNING).label == "los sábados por la mañana"


def test_spanish_help_articles_match_the_english_ones() -> None:
    assert len(ARTICLES_ES) == len(ARTICLES)
    for english, spanish in zip(ARTICLES, ARTICLES_ES, strict=True):
        assert (english.page, english.leaders_only) == (spanish.page, spanish.leaders_only)
        assert len(english.steps) == len(spanish.steps)
        assert spanish.title != english.title


def test_help_search_in_spanish(spanish: None) -> None:
    best = search_help("¿Cómo exporto un informe en PDF?", is_leader=True)[0][1]
    assert best.title == "Crear y exportar un informe"
    pronouns = search_help("pronombres", is_leader=False)[0][1]
    assert pronouns.title == "Nombres y pronombres"


# ------------------------------------------------------------- whole app


@pytest.fixture
def demo(store: DataStore, qapp: QApplication) -> Iterator[Services]:
    seed_demo_data(store, today=SEED_DAY, password_iterations=FAST_ITERATIONS)
    services = Services.create(
        store, clock=FixedClock(datetime.combine(SEED_DAY, time(8, 0))), password_iterations=FAST_ITERATIONS
    )
    theme.set_font_families(*assets.load_fonts())
    yield services
    theme.apply_appearance(qapp, Appearance(theme=Theme.LIGHT))


def test_language_is_saved_per_account_and_on_the_computer(demo: Services) -> None:
    session = demo.auth.sign_in("jordan.rivera", DEMO_PASSWORD)
    demo.settings.set_appearance(session, language=Language.SPANISH)
    assert demo.settings.appearance(session).language is Language.SPANISH
    assert demo.settings.appearance().language is Language.SPANISH  # the sign-in screen remembers it
    other = demo.auth.sign_in("priya.patel", DEMO_PASSWORD)
    demo.settings.set_appearance(other, language=Language.ENGLISH)
    assert demo.settings.appearance(session).language is Language.SPANISH


def test_sign_in_screen_language_choice(demo: Services) -> None:
    demo.settings.set_device_language(Language.SPANISH)
    assert demo.settings.appearance().language is Language.SPANISH


def test_damaged_language_setting_falls_back() -> None:
    restored = Appearance.from_settings({"language": "klingon"})
    assert restored.language is Language.ENGLISH
    assert Appearance(language=Language.SPANISH).to_settings()["language"] == "es"


def test_assistant_answers_in_spanish(demo: Services) -> None:
    session = demo.auth.sign_in("admin", DEMO_PASSWORD)
    set_language(Language.SPANISH)
    answer = demo.assistant.ask(session, "¿Cuántas horas servimos este mes?")
    assert "Los voluntarios sirvieron" in answer.text
    assert "este mes" in answer.text
    free = demo.assistant.ask(session, "¿Quién está libre el sábado por la mañana?")
    assert "sábados por la mañana" in free.text


def test_the_whole_window_is_in_spanish(demo: Services, qapp: QApplication, qtbot) -> None:  # type: ignore[no-untyped-def]
    session = demo.auth.sign_in("admin", DEMO_PASSWORD)
    demo.settings.set_appearance(session, language=Language.SPANISH, theme=Theme.LIGHT)
    theme.apply_appearance(qapp, demo.settings.appearance(session))
    assert current_language() is Language.SPANISH
    window = MainWindow(AppContext(demo, session, AppEvents()))
    qtbot.addWidget(window)
    window.resize(1360, 860)
    window.show()
    names = {button.text() for button in window.findChildren(QPushButton) if button.property("nav")}
    assert {"Panel", "Voluntarios", "Programas", "Calendario", "Informes", "Configuración"} <= names
    for key in window.pages:
        window.navigate(key)
        assert window.windowTitle().endswith("- ServeSync")
        assert window.pages[key].title in window.windowTitle()
    help_dialog = HelpDialog(session.role)
    qtbot.addWidget(help_dialog)
    assert help_dialog.windowTitle() == "Ayuda de ServeSync"
