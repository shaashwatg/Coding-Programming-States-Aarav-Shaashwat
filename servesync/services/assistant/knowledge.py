"""
How-to answers for "How do I...?" questions, found by keyword retrieval.

Each article is short (two to four steps), names the exact button to press,
and can carry an action that opens the right page. Retrieval scores each
article by the question's stemmed words, weighted so rare, specific words
("pronouns", "export") count more than common ones ("volunteer") — the idea
behind search engines' TF-IDF ranking, in a few lines.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from servesync.services.assistant.language import STOPWORDS, stems


@dataclass(frozen=True, slots=True)
class HelpArticle:
    title: str
    keywords: str  # extra words people use for this topic
    steps: tuple[str, ...]
    page: str = ""  # page key the answer can open
    leaders_only: bool = False
    action_label: str = ""


ARTICLES: tuple[HelpArticle, ...] = (
    HelpArticle(
        "Add a new volunteer",
        "register new person sign up recruit enroll create volunteer",
        (
            "Choose Add volunteer at the top right (or press Ctrl+N).",
            "Fill in the form; anything that needs fixing is explained beside the field.",
            "New people start as Applicants until you approve them.",
        ),
        "volunteers",
        True,
        "Open Volunteers",
    ),
    HelpArticle(
        "Approve an applicant",
        "approve applicant accept activate onboard orientation pending review",
        (
            "Open Volunteers and filter Status to Applicant.",
            "Select the person, then choose Approve.",
            "Approved volunteers can be scheduled right away.",
        ),
        "volunteers",
        True,
        "Open Volunteers",
    ),
    HelpArticle(
        "Create a program and its shifts",
        "program opportunity event project create new add shift shifts schedule repeat weekly every week recurring",
        (
            "Open Programs and choose New program.",
            "With the program selected, choose Add shift; tick Repeat weekly for recurring work.",
            "Programs start as drafts. Choose Publish so volunteers can see them.",
        ),
        "programs",
        True,
        "Open Programs",
    ),
    HelpArticle(
        "Sign someone up for a shift",
        "assign schedule book roster add person shift sign up volunteer",
        (
            "Open the shift from the Calendar or Programs page.",
            "On the Roster tab choose Add volunteer, or use the Smart Match tab for ranked suggestions.",
        ),
        "calendar",
        True,
        "Open Calendar",
    ),
    HelpArticle(
        "Record attendance and hours",
        "attendance check in hours served no show record log present absent",
        (
            "Open the shift once it has started.",
            "On the Roster tab mark each person Attended (with hours) or No-show.",
            "Hours count toward reports and service records as soon as they're saved.",
        ),
        "calendar",
        True,
        "Open Calendar",
    ),
    HelpArticle(
        "How Smart Match works",
        "smart match score recommend ranking points why explain algorithm factors",
        (
            "Smart Match scores each eligible person from 0 to 100 using five factors: availability (30), "
            "skills (30), reliability (20), experience (10), and fair share (10).",
            "Anyone too young, not yet approved, already booked, or double-booked is never suggested.",
            "People whose access needs a program doesn't list are shown last, with the reason — never hidden.",
        ),
    ),
    HelpArticle(
        "Run and export a report",
        "report export csv pdf excel spreadsheet print analysis data chart download customize",
        (
            "Open Reports and pick a question, a period, and optionally a program.",
            "Choose Columns to show or hide details, and click a heading to sort.",
            "Export CSV for spreadsheets or Save PDF for a printable copy; both contain exactly what you see.",
        ),
        "reports",
        True,
        "Open Reports",
    ),
    HelpArticle(
        "Get a service hours record",
        "service hours record letter certificate school scholarship verification proof community service pdf",
        (
            "Volunteers: open My hours and choose Save PDF.",
            "Leaders: open Reports, choose Service hours record, and pick the volunteer.",
            "The record lists each shift, the program, and hours, with a line for a coordinator's signature.",
        ),
        "hours",
    ),
    HelpArticle(
        "Find and sign up for a shift",
        "find shift sign up join browse open opportunity volunteer myself",
        (
            "Choose Find a shift at the top right.",
            "Shifts that fit your availability, skills, and access needs come first, with a Fit score.",
            "Select a shift and choose Sign up. If you can't, ServeSync explains why.",
        ),
        "find",
    ),
    HelpArticle(
        "Cancel a sign-up",
        "cancel drop withdraw remove can not make it sick sign up",
        (
            "On Home, select the upcoming shift and choose Cancel sign-up (any time before it starts).",
            "Your spot opens for someone else and the record is kept honestly as cancelled.",
        ),
        "home",
    ),
    HelpArticle(
        "Make the screen easier to use",
        "accessibility text size bigger font larger dark mode high contrast theme motion animation spacing "
        "dyslexia simplified layout low vision color blind screen reader messages timing",
        (
            "Open Settings, then Comfort and accessibility.",
            "Choose a theme (including High contrast or Match my computer), text up to 200%, extra letter spacing, "
            "reduced motion, a simplified layout, and how long messages stay up.",
            "Your choices follow your account to any computer.",
        ),
        "settings",
    ),
    HelpArticle(
        "Keyboard shortcuts",
        "keyboard shortcut keys hotkey mouse navigate tab without mouse",
        (
            "Ctrl+1 to Ctrl+6 open each page; Ctrl+K opens Ask ServeSync; Ctrl+N is the main action.",
            "Ctrl+F jumps to search; F1 opens help; Tab moves between controls; Esc closes a window.",
            "On a Mac, use Command where you see Ctrl.",
        ),
    ),
    HelpArticle(
        "Access needs and accommodations",
        "access need accommodation wheelchair step free disability transit bus seated quiet sensory remote "
        "cost money cannot afford",
        (
            "Volunteers can list access needs on My profile (step-free, seated tasks, transit, quiet space, "
            "no cost, or remote).",
            "Programs list what they offer on the program form.",
            "ServeSync never blocks anyone for an access need; it shows the gap so people can decide or ask.",
        ),
        "profile",
    ),
    HelpArticle(
        "Names and pronouns",
        "preferred name nickname pronouns she he they chosen name gender",
        (
            "A volunteer's profile has optional 'Name they go by' and 'Pronouns' fields.",
            "The name they go by is shown everywhere; the legal name appears only on safety records "
            "and service hours records.",
            "Pronouns are shown only if the person shares them; ServeSync never guesses.",
        ),
    ),
    HelpArticle(
        "Young volunteers",
        "minor teen age young under 18 child student parent guardian youth",
        (
            "Volunteers must be at least 14. Anyone under 18 needs a parent or guardian as emergency contact.",
            "A program can set a higher minimum age; younger volunteers are never matched to it.",
        ),
    ),
    HelpArticle(
        "Is my data safe?",
        "data privacy safe secure backup password security offline internet cloud",
        (
            "Everything stays on this computer in one file; nothing is sent over the internet.",
            "Passwords are stored as salted PBKDF2 hashes (600,000 rounds), and 5 wrong tries lock an account "
            "for 15 minutes.",
            "To back up, copy the ServeSync data folder shown in Settings.",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class _Indexed:
    article: HelpArticle
    terms: Counter[str]


def _index(articles: Sequence[HelpArticle]) -> tuple[list[_Indexed], dict[str, float]]:
    indexed = []
    document_frequency: Counter[str] = Counter()
    for article in articles:
        terms: Counter[str] = Counter()
        for weight, text in ((3, article.title), (2, article.keywords), (1, " ".join(article.steps))):
            for term in stems(text):
                if term not in STOPWORDS:
                    terms[term] += weight
        indexed.append(_Indexed(article, terms))
        document_frequency.update(set(terms))
    total = len(articles)
    idf = {term: math.log(1 + total / count) for term, count in document_frequency.items()}
    return indexed, idf


_INDEX, _IDF = _index(ARTICLES)


def search_help(question: str, *, is_leader: bool, limit: int = 3) -> list[tuple[float, HelpArticle]]:
    """Articles that best answer the question, highest relevance first."""
    terms = [term for term in stems(question) if term not in STOPWORDS]
    results = []
    for entry in _INDEX:
        if entry.article.leaders_only and not is_leader:
            continue
        score = sum(_IDF.get(term, 0.0) * min(entry.terms.get(term, 0), 3) for term in set(terms))
        if score > 0:
            results.append((round(score, 3), entry.article))
    results.sort(key=lambda pair: (-pair[0], pair[1].title))
    return results[:limit]
