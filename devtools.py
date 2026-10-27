"""
ServeSync developer & demo tools (command line).

    python devtools.py init               Create or upgrade the database
    python devtools.py seed [--if-empty]  Load the demo organization into an empty database
    python devtools.py reset --yes        Erase everything and reload fresh demo data
    python devtools.py summary            Print record counts and key totals
    python devtools.py smartmatch         Demo Smart Match on the upcoming shift with most openings
        [--shift ID] [--volunteer USERNAME] [--limit N]

Add ``--data-dir PATH`` before the command to use a different folder
(for example, a USB drive backup or a scratch folder).

Competition-day habit: run ``python devtools.py reset --yes`` right before
presenting so the demo starts from a known, clean state every time.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from servesync import __app_name__, __version__
from servesync.config import AppPaths
from servesync.core.errors import ServeSyncError
from servesync.data import LATEST_VERSION, DataStore
from servesync.data.migrations import current_version
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.logging_setup import configure_logging
from servesync.models import UserRole
from servesync.services import Services, Session, VolunteerMatch

#: Local maintenance session for this command-line tool. The desktop app only
#: ever gets sessions from AuthService.sign_in.
_MAINTENANCE_SESSION = Session(account_id=0, username="devtools", role=UserRole.ADMIN)


def _open_store(paths: AppPaths) -> DataStore:
    return DataStore.open(paths.database_file)


def cmd_init(paths: AppPaths) -> int:
    with _open_store(paths) as store:
        print(f"Database ready: {paths.database_file}")
        print(f"Schema version: {current_version(store.db)} (latest {LATEST_VERSION})")
    return 0


def cmd_seed(paths: AppPaths, *, if_empty: bool = False) -> int:
    with _open_store(paths) as store:
        if not store.is_empty():
            if if_empty:  # used by setup_mac.command: existing data is fine, keep it
                print("Demo data is already loaded; keeping your existing data.")
                return 0
            print("The database already has data. Use 'reset --yes' to start over.", file=sys.stderr)
            return 1
        print("Loading demo data (hashing demo passwords takes a moment)...")
        summary = seed_demo_data(store)
    print(
        f"Loaded {summary.volunteers} volunteers, {summary.opportunities} opportunities, "
        f"{summary.shifts} shifts, {summary.assignments} sign-ups, "
        f"{summary.hours_served:,.1f} hours served."
    )
    print(f"Demo sign-ins (password '{DEMO_PASSWORD}'): admin, coordinator, jordan.rivera, priya.patel")
    return 0


def cmd_reset(paths: AppPaths, *, confirmed: bool) -> int:
    if not confirmed:
        answer = input(f"This permanently erases {paths.database_file}. Type RESET to continue: ")
        if answer.strip() != "RESET":
            print("Reset cancelled. Nothing was changed.")
            return 1
    # SQLite in WAL mode keeps two companion files next to the database.
    for suffix in ("", "-wal", "-shm"):
        Path(f"{paths.database_file}{suffix}").unlink(missing_ok=True)
    print("Old data removed.")
    return cmd_seed(paths)


def cmd_summary(paths: AppPaths) -> int:
    with _open_store(paths) as store:
        org = store.settings.organization_name()
        volunteers = store.volunteers.count_by_status()
        opportunities = store.opportunities.count_by_status()
        assignments = store.assignments.count_by_status()
        hours = store.assignments.total_hours()
        value = hours * store.settings.volunteer_hour_value()

        print(f"{__app_name__} {__version__} - {org}")
        print(f"Data file: {paths.database_file}")
        print("Volunteers:    " + ", ".join(f"{s.label} {n}" for s, n in volunteers.items()))
        print("Opportunities: " + ", ".join(f"{s.label} {n}" for s, n in opportunities.items()))
        print("Sign-ups:      " + ", ".join(f"{s.label} {n}" for s, n in assignments.items()))
        print(f"Hours served:  {hours:,.1f}  (estimated value ${value:,.2f})")
    return 0


def _print_match(rank: int, match: VolunteerMatch) -> None:
    print(f"  {rank}. {match.volunteer.full_name:<22} score {match.score:>3}/100")
    for strength in match.strengths:
        print(f"       + {strength}")
    for concern in match.concerns:
        print(f"       ! {concern}")


def cmd_smartmatch(paths: AppPaths, *, shift_id: int | None, username: str | None, limit: int) -> int:
    with _open_store(paths) as store:
        services = Services.create(store)
        session = _MAINTENANCE_SESSION

        if username:  # shifts recommended for one volunteer
            account = store.accounts.find_by_username(username)
            if account is None or account.volunteer_id is None:
                print(f"No volunteer account named '{username}'.", file=sys.stderr)
                return 1
            volunteer = store.volunteers.get(account.volunteer_id)
            print(f"Smart Match - shifts recommended for {volunteer.full_name}:")
            for rank, pick in enumerate(
                services.matching.recommend_shifts(session, account.volunteer_id, limit=limit), 1
            ):
                shift = pick.overview.shift
                print(
                    f"  {rank}. {pick.overview.opportunity_title} - {shift.starts_at:%a %b %d, %I:%M %p}  "
                    f"score {pick.score}/100"
                )
                for reason in pick.strengths:
                    print(f"       + {reason}")
                for concern in pick.concerns:
                    print(f"       ! {concern}")
            return 0

        if shift_id is None:  # pick the upcoming shift that most needs people
            upcoming = services.opportunities.upcoming_schedule(session, days=45, only_with_openings=True)
            if not upcoming:
                print("No upcoming shifts with openings. Run 'reset --yes' to reload the demo.", file=sys.stderr)
                return 1
            shift_id = max(upcoming, key=lambda o: (o.open_spots, -o.shift.starts_at.timestamp())).shift.shift_id or 0

        overview = store.shifts.get_overview(shift_id)
        shift = overview.shift
        print(f"Smart Match - {overview.opportunity_title}")
        print(
            f"  {shift.starts_at:%A %b %d, %I:%M %p} to {shift.ends_at:%I:%M %p}  |  "
            f"{overview.filled}/{shift.capacity} filled, {overview.open_spots} open"
        )
        matches = services.matching.recommend_volunteers(session, shift_id, limit=limit)
        if not matches:
            print("  No eligible volunteers right now.")
        for rank, match in enumerate(matches, 1):
            _print_match(rank, match)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devtools.py", description=f"{__app_name__} developer tools")
    parser.add_argument("--data-dir", type=Path, help="folder holding the database (default: per-user app data)")
    parser.add_argument("--verbose", action="store_true", help="also print log messages to the console")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create or upgrade the database")
    seed = commands.add_parser("seed", help="load demo data into an empty database")
    seed.add_argument("--if-empty", action="store_true", help="succeed quietly if data already exists")
    reset = commands.add_parser("reset", help="erase all data and reload the demo")
    reset.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    commands.add_parser("summary", help="print record counts")
    match = commands.add_parser("smartmatch", help="demo the Smart Match recommendation engine")
    match.add_argument("--shift", type=int, help="shift ID to staff (default: the one with most openings)")
    match.add_argument("--volunteer", metavar="USERNAME", help="recommend shifts for this volunteer instead")
    match.add_argument("--limit", type=int, default=5, help="how many results to show (default 5)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = AppPaths.resolve(args.data_dir)
    configure_logging(paths.log_dir, verbose=args.verbose)
    try:
        if args.command == "init":
            return cmd_init(paths)
        if args.command == "seed":
            return cmd_seed(paths, if_empty=args.if_empty)
        if args.command == "reset":
            return cmd_reset(paths, confirmed=args.yes)
        if args.command == "smartmatch":
            return cmd_smartmatch(paths, shift_id=args.shift, username=args.volunteer, limit=args.limit)
        return cmd_summary(paths)
    except ServeSyncError as exc:
        # Expected problems get a clean one-line message, never a stack trace.
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
