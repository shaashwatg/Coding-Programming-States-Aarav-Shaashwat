"""
Render every major screen to PNG files (for design review, the README, and slides).

    python tools/capture_screens.py OUTPUT_FOLDER [--theme LIGHT|DARK|HIGH_CONTRAST] [--scale 1.0]

Runs against a throwaway copy of the demo data, so it never touches real records.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QWidget

from servesync.data import DataStore
from servesync.data.seed import DEMO_PASSWORD, seed_demo_data
from servesync.models import Theme
from servesync.services import Services
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.assistant_dialog import AssistantDialog
from servesync.ui.dialogs.auth_dialogs import LoginDialog
from servesync.ui.dialogs.program_dialogs import OpportunityDialog
from servesync.ui.dialogs.shift_detail import MATCH_TAB, ROSTER_TAB, ShiftDetailDialog
from servesync.ui.dialogs.volunteer_dialog import VolunteerDialog
from servesync.ui.main_window import MainWindow


def settle(app: QApplication) -> None:
    """Let layouts settle and every animation (fades, chart growth, toasts) finish."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtTest import QTest

    for _ in range(5):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QTest.qWait(700)


def save(app: QApplication, widget: QWidget, folder: Path, name: str, size: tuple[int, int] | None = None) -> None:
    if size:
        widget.resize(*size)
    widget.show()
    settle(app)
    widget.grab().save(str(folder / f"{name}.png"))
    print("saved", name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--theme", default="LIGHT")
    parser.add_argument("--scale", type=float, default=1.0)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    theme.set_font_families(*assets.load_fonts())
    with tempfile.TemporaryDirectory() as temp:
        store = DataStore.open(Path(temp) / "servesync.db")
        seed_demo_data(store, password_iterations=1_000)
        services = Services.create(store, password_iterations=1_000)
        theme.apply_theme(app, Theme(args.theme), args.scale)
        suffix = "" if args.theme == "LIGHT" and args.scale == 1.0 else f"-{args.theme.lower()}-{args.scale:g}"

        save(app, LoginDialog(services), args.output, f"01-sign-in{suffix}", (900, 560))

        def capture_role(username: str, prefix: str, extra: Callable[[AppContext, MainWindow], None]) -> None:
            session = services.auth.sign_in(username, DEMO_PASSWORD)
            ctx = AppContext(services, session, AppEvents())
            window = MainWindow(ctx)
            window.resize(1360, 860)
            for index, key in enumerate(window.pages, start=1):
                window.navigate(key)
                save(app, window, args.output, f"{prefix}-{index}-{key}{suffix}")
            extra(ctx, window)
            window.close()

        def leader_extras(ctx: AppContext, window: MainWindow) -> None:
            featured = services.dashboard.featured_event(ctx.session)
            if featured is not None:
                shift_id = featured.overview.shift.shift_id or 0
                save(
                    app,
                    ShiftDetailDialog(ctx, shift_id, start_tab=MATCH_TAB),
                    args.output,
                    f"02-9a-smart-match{suffix}",
                    (980, 760),
                )
                save(
                    app,
                    ShiftDetailDialog(ctx, shift_id, start_tab=ROSTER_TAB),
                    args.output,
                    f"02-9b-roster{suffix}",
                    (980, 700),
                )
            dialog = VolunteerDialog(ctx, None)
            dialog.first_name.setText("J0rdan")
            dialog.email.setText("jordan@gmial.com")
            dialog.phone.setText("911-555-0100")
            dialog._check_email()
            dialog._on_save()
            save(app, dialog, args.output, f"02-9c-validation{suffix}", (760, 900))
            program = services.opportunities.find_all(ctx.session)[0]
            save(app, OpportunityDialog(ctx, program), args.output, f"02-9d-program{suffix}", (760, 900))
            ask = AssistantDialog(ctx, window.commands())
            ask.ask("Which shifts need volunteers this week?")
            ask.ask("How many hours has Priya served?")
            save(app, ask, args.output, f"02-9e-ask{suffix}", (780, 720))
            window.navigate("reports")
            reports = window.pages["reports"]
            reports.kind_box.setCurrentIndex(1)  # type: ignore[attr-defined]  # Program impact
            save(app, window, args.output, f"02-9f-report-program{suffix}")
            window.ctx.events.status_message.emit("Saved servesync-program-impact.pdf.")
            save(app, window, args.output, f"02-9g-toast{suffix}")

        capture_role("coordinator", "02-leader", leader_extras)
        capture_role("priya.patel", "03-volunteer", lambda _ctx, _window: None)
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
