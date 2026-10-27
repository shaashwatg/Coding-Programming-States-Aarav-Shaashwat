"""Ask ServeSync: language understanding, privacy, and answers from live data."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest

from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import DayPart, Weekday
from servesync.services import Services, Session
from servesync.services.assistant import fuzzy_score, rank_commands
from servesync.services.assistant.knowledge import search_help
from servesync.services.assistant.language import (
    Intent,
    NamedThing,
    classify,
    find_period,
    find_slot,
    match_people,
    match_program,
    person_keys,
    program_keys,
    stem,
)
from servesync.services.assistant.service import subject_has
from tests.factories import FAST_ITERATIONS

TODAY = date(2026, 11, 4)  # a Wednesday

# ----------------------------------------------------------- language


def test_stemmer_groups_word_forms() -> None:
    assert {stem(w) for w in ("approve", "approved", "approval", "approving")} == {"approv"}
    assert stem("hours") == stem("hour") and stem("volunteers") == stem("volunteered")


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("hours this month", date(2026, 11, 1), date(2026, 11, 30)),
        ("last month", date(2026, 10, 1), date(2026, 10, 31)),
        ("this week", date(2026, 11, 2), date(2026, 11, 8)),
        ("this weekend", date(2026, 11, 7), date(2026, 11, 8)),
        ("in the past 10 days", date(2026, 10, 26), TODAY),
        ("what happened in october", date(2026, 10, 1), date(2026, 10, 31)),
        ("this school year", date(2026, 8, 1), TODAY),
    ],
)
def test_periods_are_understood(text: str, start: date, end: date) -> None:
    period = find_period(text, TODAY)
    assert period is not None and (period.start, period.end) == (start, end)


def test_may_only_counts_as_a_month_in_context() -> None:
    assert find_period("may I see my hours", TODAY) is None
    assert find_period("hours in may", TODAY) is not None


def test_slots_are_understood() -> None:
    slot = find_slot("Who is free Saturday morning?")
    assert slot is not None and slot.weekdays == (Weekday.SATURDAY,) and slot.day_part is DayPart.MORNING
    assert slot.label == "Saturday mornings"
    weekend = find_slot("anything on weekends")
    assert weekend is not None and weekend.label == "weekends"
    evenings = find_slot("weekday evenings")
    assert evenings is not None and evenings.label == "weekday evenings"
    assert find_slot("how many hours") is None


PEOPLE = [
    NamedThing(1, "Priya Patel", person_keys("Priya", "Patel")),
    NamedThing(2, "Alex Kim", person_keys("Alexander", "Kim", "Alex")),
    NamedThing(3, "Alex Moreno", person_keys("Alex", "Moreno")),
]


def test_people_match_with_typos_and_preferred_names() -> None:
    assert [p.record_id for p in match_people("hours for pryia", PEOPLE)] == [1]
    assert [p.record_id for p in match_people("how about alexander", PEOPLE)] == [2]
    assert {p.record_id for p in match_people("alex's hours", PEOPLE)} == {2, 3}  # ambiguous: ask which
    assert [p.record_id for p in match_people("alex kim", PEOPLE)] == [2]
    assert match_people("how many hours", PEOPLE) == []


def test_programs_match_by_distinctive_words() -> None:
    programs = [
        NamedThing(1, "Weekend Food Pantry Distribution", program_keys("Weekend Food Pantry Distribution")),
        NamedThing(2, "Riverside Park Cleanup", program_keys("Riverside Park Cleanup")),
    ]
    found = match_program("how is the pantry doing", programs)
    assert found is not None and found.record_id == 1
    assert match_program("how is the weekend going", programs) is None  # "weekend" is too generic


@pytest.mark.parametrize(
    ("question", "leader", "intent"),
    [
        ("Which shifts need volunteers this week?", True, Intent.SHIFTS_NEEDING_PEOPLE),
        ("Who is free Saturday morning?", True, Intent.WHO_IS_FREE),
        ("How many hours did we serve this month?", True, Intent.ORG_HOURS),
        ("how many hours has priya served", True, Intent.PERSON_HOURS),
        ("Who is waiting for approval?", True, Intent.APPLICANTS),
        ("who volunteered the most", True, Intent.TOP_VOLUNTEERS),
        ("which program delivered the most hours", True, Intent.TOP_PROGRAMS),
        ("How do I export a report?", True, Intent.HOW_TO),
        ("What should I sign up for?", False, Intent.RECOMMEND_SHIFTS),
        ("When is my next shift?", False, Intent.MY_NEXT_SHIFT),
        ("how many hours do I have", False, Intent.MY_HOURS),
        ("hello!", False, Intent.GREETING),
    ],
)
def test_intents(question: str, leader: bool, intent: Intent) -> None:
    parsed = classify(question, today=TODAY, people=PEOPLE, programs=[], is_leader=leader)
    assert parsed.intent is intent, parsed.scores


def test_nonsense_has_no_intent() -> None:
    assert classify("asdfgh qwerty", today=TODAY, people=PEOPLE, programs=[], is_leader=True).intent is None


def test_help_search_finds_the_right_article() -> None:
    assert search_help("how do I make the text bigger", is_leader=False)[0][1].title == "Make the screen easier to use"
    assert search_help("I need a wheelchair ramp", is_leader=False)[0][1].title == "Access needs and accommodations"
    leader_only = {a.title for _, a in search_help("approve applicant", is_leader=False)}
    assert "Approve an applicant" not in leader_only  # leader articles hidden from volunteers


def test_fuzzy_command_matching() -> None:
    assert fuzzy_score("rep", "Reports") == 1.0
    assert fuzzy_score("vlntr", "Volunteers") is not None
    assert fuzzy_score("xyz", "Volunteers") is None
    ranked = rank_commands("cal", ["Calendar", "Cancel sign-up", "Reports"])
    assert ranked[0][1] == "Calendar"


@pytest.mark.parametrize(
    ("pronouns", "expected"),
    [("she/her", "She has"), ("they/them", "They have"), ("", "Sam has"), ("ze/hir", "Sam has")],
)
def test_pronouns_are_used_only_when_shared(pronouns: str, expected: str) -> None:
    assert subject_has(pronouns, "Sam") == expected


# ------------------------------------------------- answers from live data


@pytest.fixture(scope="module")
def demo() -> Iterator[Services]:
    store = DataStore.in_memory()
    seed_demo_data(store, password_iterations=FAST_ITERATIONS)
    yield Services.create(store, password_iterations=FAST_ITERATIONS)
    store.close()


@pytest.fixture(scope="module")
def leader(demo: Services) -> Session:
    return demo.auth.sign_in("coordinator", DEMO_PASSWORD)


@pytest.fixture(scope="module")
def priya(demo: Services) -> Session:
    return demo.auth.sign_in("priya.patel", DEMO_PASSWORD)


def test_person_hours_match_the_database(demo: Services, leader: Session) -> None:
    priya = next(v for v in demo.store.volunteers.find_all(search="Priya Patel"))
    answer = demo.assistant.ask(leader, "How many hours has Priya served?")
    hours = demo.store.assignments.total_hours(volunteer_id=priya.volunteer_id)
    assert f"{hours:,.0f} hours" in answer.text or f"{hours:,.1f} hours" in answer.text
    assert "She has" in answer.text  # Priya shares she/her
    assert answer.actions[0].page == "reports"


def test_staffing_answer_lists_real_openings(demo: Services, leader: Session) -> None:
    answer = demo.assistant.ask(leader, "Which shifts need volunteers this week?")
    assert "spots open" in answer.text or "fully staffed" in answer.text
    assert answer.understood.startswith("shifts that need people")


def test_volunteers_cannot_ask_about_others(demo: Services, priya: Session) -> None:
    for question in ("How many hours has Jordan served?", "Who is free Saturday?", "Who is waiting for approval?"):
        answer = demo.assistant.ask(priya, question)
        assert "only coordinators" in answer.text, question


def test_volunteer_recommendations_respect_access_needs(demo: Services, priya: Session) -> None:
    answer = demo.assistant.ask(priya, "What should I sign up for?")
    assert "Habitat" not in answer.text  # Priya relies on transit; the build site isn't near it
    assert answer.actions[0].page == "find"


def test_every_suggestion_gets_a_real_answer(demo: Services, leader: Session, priya: Session) -> None:
    for session in (leader, priya):
        for question in demo.assistant.suggestions(session):
            answer = demo.assistant.ask(session, question)
            assert "not sure I understood" not in answer.text, question
            assert answer.text.strip()


def test_empty_and_overlong_questions(demo: Services, leader: Session) -> None:
    assert demo.assistant.ask(leader, "   ").follow_ups
    assert "long question" in demo.assistant.ask(leader, "why " * 100).text


def test_unknown_question_offers_suggestions(demo: Services, leader: Session) -> None:
    answer = demo.assistant.ask(leader, "zzzz qqqq")
    assert "not sure" in answer.text and answer.follow_ups
