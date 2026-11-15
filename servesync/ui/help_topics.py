"""
Help written for people, not features: how ServeSync answers the FBLA topic,
help for each page (the "?" button), and the first-run tour for each role.

Every sentence goes through ``mark``/``tr``, so it appears in English or
Spanish and the translation checks cover it like any other message.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from servesync.core.i18n import mark, tr


@dataclass(frozen=True, slots=True)
class TopicRow:
    """One phrase of the competition topic, where it lives in ServeSync, and how."""

    phrase: str
    screens: str
    how: str


#: "Serving the Community: Nonprofit Volunteer Management", phrase by phrase.
TOPIC_ROWS: tuple[TopicRow, ...] = (
    TopicRow(
        mark("Recruit volunteers"),
        mark("Sign-in screen (Become a volunteer), Dashboard, Volunteers, Reports > Recruitment channels"),
        mark(
            "Anyone can apply from the sign-in screen and name who invited them. Leaders approve applicants, "
            "import many people from a spreadsheet, and see which channels and people bring in the most volunteers."
        ),
    ),
    TopicRow(
        mark("Organize volunteers and activities"),
        mark("Programs, Calendar, Edit roles"),
        mark(
            "Programs hold the shifts; each shift can be split into roles with their own sizes and skills. "
            "The calendar shows every shift by day."
        ),
    ),
    TopicRow(
        mark("Manage volunteers"),
        mark("Volunteers, Settings > Change history, Settings > Privacy requests"),
        mark(
            "Profiles with skills, availability, access needs, certifications and waivers; approve, archive, "
            "and see who changed what. Volunteers can download or remove their own data."
        ),
    ),
    TopicRow(
        mark("Coordinate"),
        mark("Smart Match, Staffing Studio, Announce, Tomorrow's reminders, waitlists"),
        mark(
            "Smart Match ranks the best people for a shift and fills roles by skill; Autopilot drafts two weeks of "
            "sign-ups; announcements reach everyone signed up; reminders give a call list; waitlists refill shifts."
        ),
    ),
    TopicRow(
        mark("Manage service opportunities"),
        mark("Programs, shift workspace, Find a shift"),
        mark(
            "Publish, close or reopen programs; add one-time or weekly shifts; require certifications or waivers; "
            "volunteers find shifts that fit them and sign up, or join a waitlist when full."
        ),
    ),
    TopicRow(
        mark("Maintain records"),
        mark("Shift roster, check-in kiosk, sign-in sheet, My hours, Settings > Back up"),
        mark(
            "Attendance and hours are recorded on the roster or by kiosk check-in and check-out; service records "
            "and certificates carry a verification code; every record can be backed up and restored."
        ),
    ),
    TopicRow(
        mark("Monitor participation"),
        mark("Dashboard, Reports, Staffing Studio > Attendance forecast"),
        mark(
            "Live figures, five leader reports plus certification expiry and one-page impact summaries, "
            "insights in plain words, and a forecast of shifts that may come up short."
        ),
    ),
    TopicRow(
        mark("Meet the needs of volunteers"),
        mark("Home, Find a shift, My hours, My profile, Settings"),
        mark(
            "Recommendations that fit their time, skills and access needs; hour goals with a finish date; "
            "certificates; calendar files; English and Spanish; text size, high contrast and reduced motion."
        ),
    ),
    TopicRow(
        mark("Meet the needs of leaders"),
        mark("Dashboard, Ask ServeSync (Ctrl+K), Reports, Verify a record"),
        mark(
            "What needs attention today in one place, answers to plain questions, exports for funders, and a quick "
            "way to confirm a record a school or employer asks about. Everything works offline."
        ),
    ),
)


def topic_html() -> str:
    """The "How ServeSync addresses the topic" help page, in the current language."""
    e = escape
    intro = tr(
        "The FBLA 2026-2027 topic asks for a program that helps a nonprofit recruit, organize, and manage "
        "volunteers and community service activities. Here is where each part of that request lives."
    )
    rows = []
    for row in TOPIC_ROWS:
        where = tr("Where: {screens}", screens=tr(row.screens))
        rows.append(
            f"<tr><td valign='top' width='30%' style='padding:8px 12px 8px 0'><b>{e(tr(row.phrase))}</b></td>"
            f"<td valign='top' style='padding:8px 0'>{e(tr(row.how))}<br><i>{e(where)}</i></td></tr>"
        )
    return (
        f"<h2>{e(tr('How ServeSync addresses the topic'))}</h2><p>{e(intro)}</p>"
        f"<table cellspacing='0' width='100%'>{''.join(rows)}</table>"
    )


@dataclass(frozen=True, slots=True)
class PageHelp:
    title: str
    points: tuple[str, ...]


#: What each page is for and how to use it (the "?" button).
PAGE_HELP: dict[str, PageHelp] = {
    "dashboard": PageHelp(
        mark("Dashboard"),
        (
            mark("The four figures show the organization at a glance; an amber bar marks the ones that need you."),
            mark("Shifts that need people this week: double-click one to see its best matches."),
            mark("Applicants waiting for review, recent activity, and certifications running out in 30 days."),
            mark("Tomorrow's reminders gives a call list; Open check-in kiosk turns this laptop into a welcome desk."),
        ),
    ),
    "volunteers": PageHelp(
        mark("Volunteers"),
        (
            mark("Search by name, email or phone, and filter by status."),
            mark("Select a person to approve, archive, or edit them; double-click to open their profile."),
            mark("Import adds many people from a CSV file after checking every row."),
        ),
    ),
    "programs": PageHelp(
        mark("Programs"),
        (
            mark("Create a program, then publish it so volunteers can see it."),
            mark("Add one-time or weekly shifts; open a shift to edit its roles or sign people up."),
            mark("Announce posts a note for everyone signed up for the program."),
        ),
    ),
    "calendar": PageHelp(
        mark("Calendar"),
        (
            mark("Amber dots mark days with open spots; pick a day to see its shifts."),
            mark("Select a shift to see its details, sign up, or add it to your calendar."),
        ),
    ),
    "staffing": PageHelp(
        mark("Staffing Studio"),
        (
            mark("Autopilot drafts sign-ups for the next two weeks; untick anyone, then choose Sign up selected."),
            mark("The attendance forecast shows which shifts may come up short, even if they look full."),
            mark("Worth a personal invitation lists regulars who have stopped coming."),
        ),
    ),
    "reports": PageHelp(
        mark("Reports"),
        (
            mark("Pick a question and a period; every report has figures, plain-word insights, charts and a table."),
            mark("Columns and Sections choose what to show; Export CSV and Save PDF keep exactly what you see."),
            mark("Verify a record checks the code on a service record or certificate."),
        ),
    ),
    "settings": PageHelp(
        mark("Settings"),
        (
            mark("Choose your language, theme, text size, and comfort options; they follow your account."),
            mark("Administrators: organization details, backups, change history, and privacy requests."),
        ),
    ),
    "home": PageHelp(
        mark("Home"),
        (
            mark("Updates for you shows news about your shifts, such as a spot opening from a waitlist."),
            mark("Your figures, your hour goal, and the next big event."),
            mark("Your upcoming shifts (cancel or add to your calendar) and shifts recommended for you."),
        ),
    ),
    "find": PageHelp(
        mark("Find a shift"),
        (
            mark("The filters start with shifts you can join; turn one off to see more."),
            mark("Fit is your Smart Match score. Select a shift to see details and sign up."),
            mark("If a shift is full, you can join its waitlist."),
        ),
    ),
    "hours": PageHelp(
        mark("My hours"),
        (
            mark("Your verified service for the period you choose. Save PDF for school or employers."),
            mark("At 25, 50 and 100 hours, save a milestone certificate."),
        ),
    ),
    "profile": PageHelp(
        mark("My profile"),
        (
            mark("Keep your contact details, availability and skills current."),
            mark("Download my data, or ask for your personal details to be removed."),
        ),
    ),
}


def page_help_html(key: str) -> str:
    help_ = PAGE_HELP.get(key)
    if help_ is None:
        return f"<p>{escape(tr('Press F1 for all help topics.'))}</p>"
    items = "".join(f"<li>{escape(tr(point))}</li>" for point in help_.points)
    return f"<h2>{escape(tr(help_.title))}</h2><ul>{items}</ul>"


@dataclass(frozen=True, slots=True)
class TourStep:
    page: str  # the page to show for this step
    title: str
    text: str
    target: str = "nav"  # what to outline: "nav" (the page's sidebar button), "ask", "cta", or "help"


LEADER_TOUR: tuple[TourStep, ...] = (
    TourStep(
        "dashboard",
        mark("Welcome to ServeSync"),
        mark("A one-minute tour of where things are. Skip it any time; replay it from Help > Take the tour."),
    ),
    TourStep(
        "dashboard",
        mark("Start each day here"),
        mark("The Dashboard shows what needs you: applicants, shifts short of people, and expiring certifications."),
    ),
    TourStep("volunteers", mark("Your volunteers"), mark("Approve applicants, update profiles, or import a list.")),
    TourStep(
        "programs",
        mark("Programs and shifts"),
        mark("Create programs, add shifts, and split shifts into roles. Publish a program to open it."),
    ),
    TourStep(
        "staffing",
        mark("Staffing Studio"),
        mark("Autopilot drafts the next two weeks of sign-ups for you to approve."),
    ),
    TourStep("reports", mark("Reports"), mark("Answers for your board and funders, ready to save as PDF.")),
    TourStep(
        "dashboard",
        mark("Ask anything"),
        mark("Press Ctrl+K to ask a question in plain words, or to jump to any page."),
        "ask",
    ),
    TourStep(
        "dashboard",
        mark("Help on every page"),
        mark("The ? button explains the page you're on. That's the tour. Thank you for serving your community!"),
        "help",
    ),
)

VOLUNTEER_TOUR: tuple[TourStep, ...] = (
    TourStep(
        "home",
        mark("Welcome to ServeSync"),
        mark("A one-minute tour of where things are. Skip it any time; replay it from Help > Take the tour."),
    ),
    TourStep(
        "home",
        mark("Your home"),
        mark("Your upcoming shifts, your hours, news about your shifts, and shifts picked for you."),
    ),
    TourStep(
        "find",
        mark("Find a shift"),
        mark("Browse shifts that fit your time and skills, then sign up. Full? Join the waitlist."),
        "cta",
    ),
    TourStep("hours", mark("My hours"), mark("Your verified service, ready as a PDF, and certificates at milestones.")),
    TourStep("profile", mark("My profile"), mark("Keep your availability current so recommendations fit your life.")),
    TourStep(
        "home",
        mark("Help on every page"),
        mark("The ? button explains the page you're on. That's the tour. Thank you for volunteering!"),
        "help",
    ),
)
