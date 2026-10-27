"""
Understanding a typed question — pure functions, no database.

ServeSync's assistant works fully **offline** (conference Wi-Fi is unreliable,
and a nonprofit's volunteer data shouldn't leave the building). Instead of a
cloud language model it uses classic, explainable techniques:

1. **Normalize** — lower-case, expand contractions, drop punctuation.
2. **Stem** — "volunteered", "volunteering", "volunteers" -> "volunteer".
3. **Extract entities** — dates ("this month", "in October"), time slots
   ("Saturday morning"), people (with typo tolerance: "Pryia" -> Priya), and
   programs (by their distinctive words).
4. **Classify intent** — each intent has weighted cue words; the best score
   wins, and entities break ties (a named person + "hours" = that person's hours).

Every answer says what it understood ("I read this as: hours for Priya Patel,
this month"), so a wrong guess is obvious and easy to rephrase.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from servesync.models import DayPart, Weekday

# ------------------------------------------------------------ normalizing

_CONTRACTIONS = {
    "what's": "what is",
    "who's": "who is",
    "where's": "where is",
    "when's": "when is",
    "how's": "how is",
    "i'm": "i am",
    "i've": "i have",
    "can't": "can not",
    "don't": "do not",
    "isn't": "is not",
    "didn't": "did not",
    "haven't": "have not",
    "we've": "we have",
    "let's": "let us",
}
_WORD = re.compile(r"[a-z0-9']+")

# fmt: off
STOPWORDS = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "could", "did", "do", "does", "for", "from",
    "get", "give", "got", "has", "have", "how", "i", "in", "is", "it", "its", "me", "my", "of", "on", "or",
    "our", "please", "show", "tell", "than", "that", "the", "their", "them", "there", "these", "they", "this",
    "to", "us", "was", "we", "were", "what", "when", "where", "which", "who", "whom", "why", "will", "with",
    "would", "you", "your",
])
# fmt: on


def normalize(text: str) -> str:
    lowered = text.lower().replace("’", "'")
    for short, full in _CONTRACTIONS.items():
        lowered = lowered.replace(short, full)
    return " ".join(_WORD.findall(lowered))


_SUFFIXES = ("ings", "ing", "edly", "ed", "ies", "es", "al", "s", "e")


def stem(word: str) -> str:
    """
    A tiny suffix-stripping stemmer, good enough for short questions:
    approve / approved / approval / approving -> "approv".
    """
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            base = word[: -len(suffix)]
            return base + "y" if suffix == "ies" else base
    return word


def stems(text: str) -> list[str]:
    return [stem(word) for word in normalize(text).split()]


# ---------------------------------------------------------------- periods


@dataclass(frozen=True, slots=True)
class Period:
    start: date
    end: date
    label: str


_MONTHS = {
    name: index
    for index, names in enumerate(
        [
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ],
        start=1,
    )
    for name in names
}


def _month_end(year: int, month: int) -> date:
    following = date(year + (month == 12), month % 12 + 1, 1)
    return following - timedelta(days=1)


def find_period(text: str, today: date) -> Period | None:
    """A date range mentioned in the question, or None."""
    t = f" {normalize(text)} "
    monday = today - timedelta(days=today.weekday())
    checks: list[tuple[str, Period]] = [
        (" today ", Period(today, today, "today")),
        (" tomorrow ", Period(today + timedelta(days=1), today + timedelta(days=1), "tomorrow")),
        (" yesterday ", Period(today - timedelta(days=1), today - timedelta(days=1), "yesterday")),
        (" next week ", Period(monday + timedelta(days=7), monday + timedelta(days=13), "next week")),
        (" last week ", Period(monday - timedelta(days=7), monday - timedelta(days=1), "last week")),
        (" this weekend ", Period(monday + timedelta(days=5), monday + timedelta(days=6), "this weekend")),
        (" weekend ", Period(monday + timedelta(days=5), monday + timedelta(days=6), "this weekend")),
        (" this week ", Period(monday, monday + timedelta(days=6), "this week")),
        (" last month ", _last_month(today)),
        (" this month ", Period(today.replace(day=1), _month_end(today.year, today.month), "this month")),
        (" school year ", _school_year(today)),
        (" last year ", Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), f"in {today.year - 1}")),
        (" this year ", Period(date(today.year, 1, 1), today, "this year")),
        (" all time ", Period(date(2000, 1, 1), today, "all time")),
        (" ever ", Period(date(2000, 1, 1), today, "all time")),
    ]
    for phrase, period in checks:
        if phrase in t:
            return period
    days = re.search(r" (?:last|past) (\d{1,3}) days ", t)
    if days:
        count = max(1, min(int(days.group(1)), 1000))
        return Period(today - timedelta(days=count - 1), today, f"the last {count} days")
    for word in t.split():
        month = _MONTHS.get(word)
        if month is not None and (word != "may" or re.search(r" (?:in|during|for) may ", t)):
            year = today.year if month <= today.month else today.year - 1
            return Period(date(year, month, 1), min(_month_end(year, month), today), f"in {date(year, month, 1):%B %Y}")
    return None


def _last_month(today: date) -> Period:
    end = today.replace(day=1) - timedelta(days=1)
    return Period(end.replace(day=1), end, "last month")


def _school_year(today: date) -> Period:
    year = today.year if today.month >= 8 else today.year - 1
    return Period(date(year, 8, 1), today, "this school year")


# ------------------------------------------------------------------ slots


@dataclass(frozen=True, slots=True)
class Slot:
    weekdays: tuple[Weekday, ...]
    day_part: DayPart | None

    @property
    def label(self) -> str:
        """'Saturdays', 'Saturday mornings', 'weekday evenings', 'Monday or Friday afternoons'."""
        days = set(self.weekdays)
        if days == {d for d in Weekday if d < Weekday.SATURDAY}:
            day_text = "weekday"
        elif days == {Weekday.SATURDAY, Weekday.SUNDAY}:
            day_text = "weekend"
        elif days:
            day_text = " or ".join(d.label for d in self.weekdays)
        else:
            day_text = "any day"
        if self.day_part is not None:
            return f"{day_text} {self.day_part.label.lower()}s"
        return day_text if day_text == "any day" else f"{day_text}s"


_WEEKDAY_WORDS = {
    **{day.name.lower(): day for day in Weekday},
    **{day.name.lower() + "s": day for day in Weekday},
    **{day.name.lower()[:3]: day for day in Weekday},
    "tues": Weekday.TUESDAY,
    "weds": Weekday.WEDNESDAY,
    "thurs": Weekday.THURSDAY,
}
_PART_WORDS = {
    "morning": DayPart.MORNING,
    "mornings": DayPart.MORNING,
    "am": DayPart.MORNING,
    "afternoon": DayPart.AFTERNOON,
    "afternoons": DayPart.AFTERNOON,
    "evening": DayPart.EVENING,
    "evenings": DayPart.EVENING,
    "night": DayPart.EVENING,
    "tonight": DayPart.EVENING,
}


def find_slot(text: str) -> Slot | None:
    """Weekday(s) and/or time of day mentioned ("Saturday morning", "weekends")."""
    words = normalize(text).split()
    days: list[Weekday] = []
    part: DayPart | None = None
    for word in words:
        day = _WEEKDAY_WORDS.get(word)
        if day is not None and day not in days:
            days.append(day)
        if word in ("weekend", "weekends"):
            days.extend(d for d in (Weekday.SATURDAY, Weekday.SUNDAY) if d not in days)
        if word in ("weekday", "weekdays"):
            days.extend(d for d in Weekday if d < Weekday.SATURDAY and d not in days)
        part = _PART_WORDS.get(word, part)
    if not days and part is None:
        return None
    return Slot(tuple(sorted(days)), part)


# --------------------------------------------------------- people/programs


@dataclass(frozen=True, slots=True)
class NamedThing:
    """Something the question might refer to by name (a volunteer or a program)."""

    record_id: int
    display: str
    keys: tuple[str, ...]  # lower-case words that identify it


def person_keys(first: str, last: str, preferred: str = "") -> tuple[str, ...]:
    names = {first.lower(), last.lower()}
    if preferred:
        names.add(preferred.lower())
    return tuple(sorted(word for name in names for word in normalize(name).split() if len(word) > 1))


# fmt: off
_GENERIC_PROGRAM_WORDS = frozenset([
    "day", "days", "weekend", "weekly", "program", "programs", "event", "events", "shift", "shifts",
    "volunteer", "volunteers", "support", "community", "the", "and", "of", "for", "at",
])
# fmt: on


def program_keys(title: str) -> tuple[str, ...]:
    return tuple(sorted({stem(w) for w in normalize(title).split() if w not in _GENERIC_PROGRAM_WORDS and len(w) > 2}))


def match_people(text: str, people: Sequence[NamedThing]) -> list[NamedThing]:
    """
    People named in the question. Exact name words count double; close
    misspellings (similarity >= 0.75, e.g. "Pryia" for "Priya") count once. Returns the best-scoring
    people (several when the question is ambiguous, e.g. two "Alex"es).
    """
    words = [w.rstrip("'s") if w.endswith("'s") else w for w in normalize(text).split()]
    words = [w for w in words if w not in STOPWORDS and len(w) > 1]
    scores: dict[int, float] = {}
    for person in people:
        score = 0.0
        for word in words:
            if word in person.keys:
                score += 2
            elif len(word) >= 4 and difflib.get_close_matches(word, person.keys, n=1, cutoff=0.75):
                score += 1
        if score:
            scores[person.record_id] = score
    if not scores:
        return []
    best = max(scores.values())
    return [p for p in people if scores.get(p.record_id) == best]


def match_program(text: str, programs: Sequence[NamedThing]) -> NamedThing | None:
    """The program whose distinctive words best match the question (unique best only)."""
    words = set(stems(text))
    scored = [(len(words & set(program.keys)), program) for program in programs]
    scored = [(score, program) for score, program in scored if score]
    if not scored:
        return None
    best = max(score for score, _ in scored)
    winners = [program for score, program in scored if score == best]
    return winners[0] if len(winners) == 1 else None


# ---------------------------------------------------------------- intents


class Intent(Enum):
    MY_HOURS = "your service hours"
    MY_NEXT_SHIFT = "your upcoming shifts"
    RECOMMEND_SHIFTS = "shifts that suit you"
    PERSON_HOURS = "a volunteer's hours"
    ORG_HOURS = "total hours served"
    WHO_IS_FREE = "who is available"
    SHIFTS_NEEDING_PEOPLE = "shifts that need people"
    TOP_VOLUNTEERS = "top volunteers"
    VOLUNTEER_COUNTS = "volunteer counts"
    APPLICANTS = "applicants waiting for review"
    PROGRAM_STATUS = "how a program is doing"
    TOP_PROGRAMS = "programs with the most impact"
    HOW_TO = "how to use ServeSync"
    GREETING = "a greeting"
    THANKS = "thanks"


#: Cue words and their weights for each intent (stemmed once, below).
_CUE_WORDS: dict[Intent, dict[str, float]] = {
    Intent.MY_HOURS: {"hours": 2, "served": 1, "total": 1, "certificate": 2, "record": 1, "letter": 2},
    Intent.MY_NEXT_SHIFT: {"next": 2, "upcoming": 2, "scheduled": 1, "shift": 1, "when": 1},
    Intent.RECOMMEND_SHIFTS: {
        "recommend": 3,
        "suggest": 3,
        "find": 2,
        "should": 1,
        "open": 1,
        "shift": 1,
        "opportunity": 1,
        "join": 2,
        "help": 0.5,
        "available": 1,
        "something": 1,
    },
    Intent.PERSON_HOURS: {"hours": 2, "served": 1, "volunteered": 1, "total": 1},
    Intent.ORG_HOURS: {
        "hours": 2,
        "total": 1,
        "impact": 2.5,
        "value": 1.5,
        "served": 1,
        "organization": 1,
        "we": 1,
        "all": 0.5,
    },
    Intent.WHO_IS_FREE: {"free": 3, "available": 3, "availability": 3, "who": 1, "cover": 1.5},
    Intent.SHIFTS_NEEDING_PEOPLE: {
        "need": 2.5,
        "short": 2,
        "understaffed": 3,
        "unfilled": 3,
        "empty": 2,
        "open": 1,
        "spots": 1.5,
        "shift": 1,
        "fill": 1.5,
        "staffed": 1.5,
    },
    Intent.TOP_VOLUNTEERS: {"most": 2, "top": 2.5, "best": 1.5, "leaderboard": 3, "star": 1, "who": 0.5},
    Intent.VOLUNTEER_COUNTS: {"many": 1.5, "count": 2, "number": 1.5, "volunteers": 1, "active": 1.5},
    Intent.APPLICANTS: {"applicants": 3, "approve": 2.5, "approval": 2.5, "pending": 2, "review": 2, "waiting": 1.5},
    Intent.PROGRAM_STATUS: {"doing": 2, "stats": 1.5, "about": 1, "going": 1.5, "fill": 1, "info": 1.5},
    Intent.TOP_PROGRAMS: {"program": 2, "programs": 2, "most": 1.5, "top": 1.5, "best": 1.5, "impact": 1, "which": 1},
    Intent.HOW_TO: {
        "how": 1.5,
        "where": 1,
        "change": 1,
        "add": 1,
        "create": 1,
        "make": 0.5,
        "explain": 2,
        "help": 1,
        "mean": 1.5,
        "work": 1,
        "use": 1,
        "set": 0.5,
        "what": 0.5,
    },
    Intent.GREETING: {"hi": 3, "hello": 3, "hey": 3},
    Intent.THANKS: {"thank": 4, "thanks": 4, "thx": 4},
}

_CUES: dict[Intent, dict[str, float]] = {
    intent: {stem(word): weight for word, weight in cues.items()} for intent, cues in _CUE_WORDS.items()
}

_SELF_WORDS = frozenset({"i", "me", "my", "mine", "myself"})
_LEADER_ONLY = frozenset(
    {
        Intent.PERSON_HOURS,
        Intent.ORG_HOURS,
        Intent.WHO_IS_FREE,
        Intent.TOP_VOLUNTEERS,
        Intent.VOLUNTEER_COUNTS,
        Intent.APPLICANTS,
        Intent.PROGRAM_STATUS,
        Intent.TOP_PROGRAMS,
        Intent.SHIFTS_NEEDING_PEOPLE,
    }
)

#: Phrases that mark a how-to question ("How do I add a volunteer?").
_HOW_TO_PHRASES = (
    " how do i ",
    " how can i ",
    " how to ",
    " how do you ",
    " where do i ",
    " where can i ",
    " what does ",
    " what is a ",
    " can i ",
    " how does ",
)


def is_leader_only(intent: Intent) -> bool:
    return intent in _LEADER_ONLY


@dataclass(frozen=True, slots=True)
class ParsedQuestion:
    text: str
    intent: Intent | None
    period: Period | None = None
    slot: Slot | None = None
    people: tuple[NamedThing, ...] = ()
    program: NamedThing | None = None
    about_self: bool = False
    scores: dict[Intent, float] = field(default_factory=dict)


def classify(
    text: str,
    *,
    today: date,
    people: Sequence[NamedThing],
    programs: Sequence[NamedThing],
    is_leader: bool,
) -> ParsedQuestion:
    """Work out what the person is asking for, and about whom/what/when."""
    words = normalize(text).split()
    word_stems = [stem(w) for w in words]
    about_self = any(w in _SELF_WORDS for w in words)
    period = find_period(text, today)
    slot = find_slot(text)
    found_people = tuple(match_people(text, people))
    program = match_program(text, programs)

    scores: dict[Intent, float] = {}
    for intent, cues in _CUES.items():
        score = sum(cues.get(s, 0.0) for s in word_stems)
        scores[intent] = score

    # Entities and role refine the raw cue scores. Boosts only apply to an
    # intent that already has a cue word, so "I" alone never decides anything.
    def boost(intent: Intent, amount: float) -> None:
        if scores[intent] > 0:
            scores[intent] += amount

    padded = f" {' '.join(words)} "
    if found_people:
        boost(Intent.PERSON_HOURS, 3)
    else:
        scores[Intent.PERSON_HOURS] = 0
    if program is not None:
        scores[Intent.PROGRAM_STATUS] += 2.5
        scores[Intent.TOP_PROGRAMS] = 0
    if slot is not None:
        boost(Intent.WHO_IS_FREE, 1.5)
        boost(Intent.RECOMMEND_SHIFTS, 1)
    if about_self or not is_leader:
        for intent in (Intent.MY_HOURS, Intent.MY_NEXT_SHIFT, Intent.RECOMMEND_SHIFTS):
            boost(intent, 2 if about_self else 0.5)
        scores[Intent.ORG_HOURS] -= 2
    else:
        scores[Intent.MY_HOURS] = 0
        scores[Intent.MY_NEXT_SHIFT] = 0
    if " how many " in padded and stem("hours") in word_stems:
        scores[Intent.VOLUNTEER_COUNTS] -= 2
    if any(phrase in padded for phrase in _HOW_TO_PHRASES) and " how many " not in padded:
        scores[Intent.HOW_TO] += 4
    if not is_leader:  # volunteers' questions are about their own service
        for intent in _LEADER_ONLY:
            scores[intent] *= 0.6

    best_intent, best_score = max(scores.items(), key=lambda item: item[1])
    return ParsedQuestion(
        text=text,
        intent=best_intent if best_score >= 2 else None,
        period=period,
        slot=slot,
        people=found_people,
        program=program,
        about_self=about_self,
        scores=scores,
    )


# ------------------------------------------------------------ fuzzy match


def fuzzy_score(query: str, candidate: str) -> float | None:
    """
    Score how well ``query`` matches ``candidate`` for the command list
    (0-1, or None for no match). Every query character must appear in order;
    matches at word starts and consecutive runs score higher — the same idea
    behind code editors' "Go to file" boxes.
    """
    q = query.lower().strip()
    c = candidate.lower()
    if not q:
        return None
    if q in c:
        return 1.0 if c.startswith(q) else 0.9 - 0.3 * (c.index(q) / max(len(c), 1))
    position = 0
    score = 0.0
    previous = -2
    for char in q:
        if char == " ":
            continue
        index = c.find(char, position)
        if index < 0:
            return None
        at_word_start = index == 0 or not c[index - 1].isalnum()
        score += 1.0 + (1.0 if at_word_start else 0.0) + (0.5 if index == previous + 1 else 0.0)
        previous = index
        position = index + 1
    letters = sum(1 for ch in q if ch != " ")
    return round(min(0.85, score / (letters * 2.5)), 3)


def rank_commands(query: str, labels: Iterable[str], limit: int = 6) -> list[tuple[float, str]]:
    ranked = [(score, label) for label in labels if (score := fuzzy_score(query, label)) is not None]
    ranked.sort(key=lambda pair: (-pair[0], pair[1]))
    return ranked[:limit]
