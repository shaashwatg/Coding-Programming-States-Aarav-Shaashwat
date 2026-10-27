"""
Understanding a typed question — pure functions, no database.

ServeSync's assistant works fully **offline** (conference Wi-Fi is unreliable,
and a nonprofit's volunteer data shouldn't leave the building). Instead of a
cloud language model it uses classic, explainable techniques:

1. **Normalize** — lower-case, expand contractions, fold accents
   ("sábado" -> "sabado"), drop punctuation.
2. **Stem** — "volunteered", "volunteering", "volunteers" -> "volunteer".
3. **Extract entities** — dates ("this month", "in October"), time slots
   ("Saturday morning"), people (with typo tolerance: "Pryia" -> Priya), and
   programs (by their distinctive words).
4. **Classify intent** — each intent has weighted cue words; the best score
   wins, and entities break ties (a named person + "hours" = that person's hours).

Questions are understood in **English or Spanish**, whichever language the
interface shows: each cue list below has both, so "¿Cuántas horas tengo?"
and "How many hours do I have?" reach the same answer.

Every answer says what it understood ("I read this as: hours for Priya Patel,
this month"), so a wrong guess is obvious and easy to rephrase.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from servesync.core.i18n import Language, current_language, month_name, tr, weekday_plural
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
    # Spanish
    "al", "como", "con", "cual", "cuales", "de", "del", "el", "en", "es", "esta", "estan", "este", "esto",
    "hay", "la", "las", "lo", "los", "mi", "mis", "muestrame", "o", "para", "pero", "por", "porfa", "que",
    "quien", "quienes", "se", "son", "su", "sus", "tengo", "tiene", "tienen", "tu", "un", "una", "y", "yo",
])
# fmt: on


def fold_accents(text: str) -> str:
    """'sábado' -> 'sabado', 'mañana' -> 'manana' (people often skip accents when typing)."""
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def normalize(text: str) -> str:
    lowered = fold_accents(text.lower().replace("’", "'"))
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
    label: str  # in the interface language, ready to drop into a sentence: "this month" / "este mes"


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
} | {
    name: index
    for index, names in enumerate(
        [
            ("enero", "ene"),
            ("febrero",),
            ("marzo",),
            ("abril", "abr"),
            ("mayo",),
            ("junio",),
            ("julio",),
            ("agosto", "ago"),
            ("septiembre", "setiembre"),
            ("octubre",),
            ("noviembre",),
            ("diciembre", "dic"),
        ],
        start=1,
    )
    for name in names
}

#: "mañana" alone means tomorrow, but "por la mañana" means in the morning.
_SPANISH_MORNING = re.compile(r" (?:por|en|de) la manana ")


def _month_end(year: int, month: int) -> date:
    following = date(year + (month == 12), month % 12 + 1, 1)
    return following - timedelta(days=1)


def find_period(text: str, today: date) -> Period | None:
    """A date range mentioned in the question, or None."""
    t = _SPANISH_MORNING.sub(" ", f" {normalize(text)} ")
    monday = today - timedelta(days=today.weekday())
    tomorrow = Period(today + timedelta(days=1), today + timedelta(days=1), tr("tomorrow"))
    yesterday = Period(today - timedelta(days=1), today - timedelta(days=1), tr("yesterday"))
    next_week = Period(monday + timedelta(days=7), monday + timedelta(days=13), tr("next week"))
    last_week = Period(monday - timedelta(days=7), monday - timedelta(days=1), tr("last week"))
    weekend = Period(monday + timedelta(days=5), monday + timedelta(days=6), tr("this weekend"))
    this_week = Period(monday, monday + timedelta(days=6), tr("this week"))
    this_month = Period(today.replace(day=1), _month_end(today.year, today.month), tr("this month"))
    last_year = Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), tr("in {year}", year=today.year - 1))
    this_year = Period(date(today.year, 1, 1), today, tr("this year"))
    all_time = Period(date(2000, 1, 1), today, tr("all time"))
    # Longer phrases first, so "next week" wins over "week" and "el mes pasado" over "mes".
    checks: list[tuple[str, Period]] = [
        (" today ", Period(today, today, tr("today"))),
        (" hoy ", Period(today, today, tr("today"))),
        (" tomorrow ", tomorrow),
        (" pasado manana ", Period(today + timedelta(days=2), today + timedelta(days=2), tr("the day after tomorrow"))),
        (" manana ", tomorrow),
        (" yesterday ", yesterday),
        (" ayer ", yesterday),
        (" next week ", next_week),
        (" proxima semana ", next_week),
        (" semana que viene ", next_week),
        (" semana proxima ", next_week),
        (" last week ", last_week),
        (" semana pasada ", last_week),
        (" this weekend ", weekend),
        (" weekend ", weekend),
        (" fin de semana ", weekend),
        (" this week ", this_week),
        (" esta semana ", this_week),
        (" last month ", _last_month(today)),
        (" mes pasado ", _last_month(today)),
        (" this month ", this_month),
        (" este mes ", this_month),
        (" school year ", _school_year(today)),
        (" ano escolar ", _school_year(today)),
        (" curso escolar ", _school_year(today)),
        (" last year ", last_year),
        (" ano pasado ", last_year),
        (" this year ", this_year),
        (" este ano ", this_year),
        (" all time ", all_time),
        (" ever ", all_time),
        (" siempre ", all_time),
        (" de todos los tiempos ", all_time),
    ]
    for phrase, period in checks:
        if phrase in t:
            return period
    days = re.search(r" (?:(?:last|past) (\d{1,3}) days|(?:ultimos|pasados) (\d{1,3}) dias) ", t)
    if days:
        count = max(1, min(int(days.group(1) or days.group(2)), 1000))
        return Period(today - timedelta(days=count - 1), today, tr("the last {count} days", count=count))
    for word in t.split():
        month = _MONTHS.get(word)
        if month is not None and (word != "may" or re.search(r" (?:in|during|for) may ", t)):
            year = today.year if month <= today.month else today.year - 1
            label = tr("in {month} {year}", month=month_name(month), year=year)
            return Period(date(year, month, 1), min(_month_end(year, month), today), label)
    return None


def _last_month(today: date) -> Period:
    end = today.replace(day=1) - timedelta(days=1)
    return Period(end.replace(day=1), end, tr("last month"))


def _school_year(today: date) -> Period:
    year = today.year if today.month >= 8 else today.year - 1
    return Period(date(year, 8, 1), today, tr("this school year"))


# ------------------------------------------------------------------ slots


@dataclass(frozen=True, slots=True)
class Slot:
    weekdays: tuple[Weekday, ...]
    day_part: DayPart | None

    @property
    def label(self) -> str:
        """
        'Saturdays', 'Saturday mornings', 'weekday evenings', 'Monday or Friday afternoons';
        in Spanish 'los sábados', 'los sábados por la mañana', 'entre semana por la noche'.
        """
        if current_language() is Language.SPANISH:
            return self._spanish_label()
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

    def _spanish_label(self) -> str:
        days = set(self.weekdays)
        if days == {d for d in Weekday if d < Weekday.SATURDAY}:
            day_text = "entre semana"
        elif days == {Weekday.SATURDAY, Weekday.SUNDAY}:
            day_text = "los fines de semana"
        elif days:
            day_text = "los " + " o ".join(weekday_plural(int(d)) for d in self.weekdays)
        else:
            day_text = "cualquier día"
        part = (
            {
                DayPart.MORNING: "por la mañana",
                DayPart.AFTERNOON: "por la tarde",
                DayPart.EVENING: "por la noche",
            }.get(self.day_part)
            if self.day_part is not None
            else None
        )
        return f"{day_text} {part}" if part else day_text


_WEEKDAY_WORDS = {
    **{day.name.lower(): day for day in Weekday},
    **{day.name.lower() + "s": day for day in Weekday},
    **{day.name.lower()[:3]: day for day in Weekday},
    "tues": Weekday.TUESDAY,
    "weds": Weekday.WEDNESDAY,
    "thurs": Weekday.THURSDAY,
    # Spanish (accents already folded away by normalize)
    "lunes": Weekday.MONDAY,
    "martes": Weekday.TUESDAY,
    "miercoles": Weekday.WEDNESDAY,
    "jueves": Weekday.THURSDAY,
    "viernes": Weekday.FRIDAY,
    "sabado": Weekday.SATURDAY,
    "sabados": Weekday.SATURDAY,
    "domingo": Weekday.SUNDAY,
    "domingos": Weekday.SUNDAY,
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
    "mananas": DayPart.MORNING,
    "tarde": DayPart.AFTERNOON,
    "tardes": DayPart.AFTERNOON,
    "noche": DayPart.EVENING,
    "noches": DayPart.EVENING,
}


def find_slot(text: str) -> Slot | None:
    """Weekday(s) and/or time of day mentioned ("Saturday morning", "weekends")."""
    padded = f" {normalize(text)} "
    if _SPANISH_MORNING.search(padded):
        padded = _SPANISH_MORNING.sub(" mornings ", padded)
    padded = padded.replace(" fin de semana ", " weekend ").replace(" fines de semana ", " weekends ")
    padded = padded.replace(" entre semana ", " weekdays ")
    words = padded.split()
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
    "programa", "programas", "evento", "eventos", "turno", "turnos", "voluntario", "voluntarios",
    "comunidad", "del", "las", "los", "como", "esta", "esto", "este", "hay", "para", "que",
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

#: Spanish cue words (accents folded), merged into the English lists above.
_SPANISH_CUE_WORDS: dict[Intent, dict[str, float]] = {
    Intent.MY_HOURS: {"horas": 2, "servicio": 1, "certificado": 2, "constancia": 2, "carta": 2, "registro": 1},
    Intent.MY_NEXT_SHIFT: {
        "proximo": 2,
        "proxima": 2,
        "siguiente": 2,
        "programado": 1,
        "inscrito": 1,
        "turno": 1,
        "cuando": 1,
    },
    Intent.RECOMMEND_SHIFTS: {
        "recomienda": 3,
        "recomiendas": 3,
        "recomendar": 3,
        "sugiere": 3,
        "sugerir": 3,
        "buscar": 2,
        "encontrar": 2,
        "deberia": 1,
        "abierto": 1,
        "turno": 1,
        "oportunidad": 1,
        "unirme": 2,
        "inscribirme": 2,
        "ayudar": 0.5,
        "algo": 1,
    },
    Intent.PERSON_HOURS: {"horas": 2, "servido": 1},
    Intent.ORG_HOURS: {
        "horas": 2,
        "impacto": 2.5,
        "valor": 1.5,
        "servido": 1,
        "organizacion": 1,
        "nosotros": 1,
        "todos": 0.5,
    },
    Intent.WHO_IS_FREE: {
        "libre": 3,
        "libres": 3,
        "disponible": 3,
        "disponibles": 3,
        "disponibilidad": 3,
        "quien": 1,
        "quienes": 1,
        "cubrir": 1.5,
    },
    Intent.SHIFTS_NEEDING_PEOPLE: {
        "necesita": 2.5,
        "necesitan": 2.5,
        "falta": 2,
        "faltan": 2,
        "vacios": 2,
        "vacantes": 3,
        "cupos": 1.5,
        "lugares": 1.5,
        "llenar": 1.5,
    },
    Intent.TOP_VOLUNTEERS: {"mas": 2, "mejores": 1.5, "ranking": 3, "clasificacion": 2, "estrella": 1},
    Intent.VOLUNTEER_COUNTS: {
        "cuantos": 1.5,
        "cuantas": 1.5,
        "numero": 1.5,
        "cantidad": 2,
        "voluntarios": 1,
        "activos": 1.5,
    },
    Intent.APPLICANTS: {
        "solicitantes": 3,
        "solicitudes": 3,
        "aprobar": 2.5,
        "aprobacion": 2.5,
        "pendiente": 2,
        "pendientes": 2,
        "revisar": 2,
        "esperando": 1.5,
    },
    Intent.PROGRAM_STATUS: {"va": 1.5, "estadisticas": 1.5, "informacion": 1.5, "sobre": 1, "marcha": 1.5},
    Intent.TOP_PROGRAMS: {
        "programa": 2,
        "programas": 2,
        "mas": 1.5,
        "mejores": 1.5,
        "impacto": 1,
        "cual": 1,
        "cuales": 1,
    },
    Intent.HOW_TO: {
        "como": 1.5,
        "donde": 1,
        "cambiar": 1,
        "agregar": 1,
        "anadir": 1,
        "crear": 1,
        "hacer": 0.5,
        "explica": 2,
        "explicar": 2,
        "ayuda": 1,
        "significa": 1.5,
        "funciona": 1,
        "usar": 1,
        "que": 0.5,
    },
    Intent.GREETING: {"hola": 3, "buenas": 3, "buenos": 2},
    Intent.THANKS: {"gracias": 4},
}
for _intent, _words in _SPANISH_CUE_WORDS.items():
    for _word, _weight in _words.items():
        _CUE_WORDS[_intent].setdefault(_word, _weight)

_CUES: dict[Intent, dict[str, float]] = {
    intent: {stem(word): weight for word, weight in cues.items()} for intent, cues in _CUE_WORDS.items()
}

_SELF_WORDS = frozenset({"i", "me", "my", "mine", "myself", "yo", "mi", "mis", "mio", "tengo", "conmigo"})
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
    " como puedo ",
    " como se ",
    " como hago ",
    " como funciona ",
    " donde puedo ",
    " donde esta ",
    " que significa ",
    " que es un ",
    " que es una ",
    " puedo ",
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
    how_many = any(phrase in padded for phrase in (" how many ", " cuantos ", " cuantas "))
    if how_many and (stem("hours") in word_stems or stem("horas") in word_stems):
        scores[Intent.VOLUNTEER_COUNTS] -= 2
    # Spanish puts the verb straight after "cómo": "¿Cómo exporto un informe?" (but "¿Cómo va...?" asks for status).
    spanish_how_to = re.match(r" como (?!va |van |esta |estan |le |les |me |nos )", padded) is not None
    if (spanish_how_to or any(phrase in padded for phrase in _HOW_TO_PHRASES)) and not how_many:
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
