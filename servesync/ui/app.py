"""
Application start-up and the sign-in / sign-out cycle.

Order of start-up:
1. Find the per-user data folder and start the log file.
2. Open (and if needed upgrade) the database. A problem here gets a clear
   message and a clean exit, never a stack trace.
3. Load fonts and apply this computer's most recent comfort settings
   (each person's own settings take over the moment they sign in).
4. Install a last-resort error handler: anything unexpected is logged and
   explained politely, and the app keeps running.
5. First launch: set up an organization or load the demo. Then sign in.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from servesync import __app_name__, __version__
from servesync.config import AppPaths
from servesync.core.errors import DataStoreError
from servesync.core.i18n import Language, catalog, current_language, tr
from servesync.data import DataStore
from servesync.logging_setup import configure_logging
from servesync.models import Theme
from servesync.services import Services, Session
from servesync.ui import assets, theme
from servesync.ui.context import AppContext, AppEvents
from servesync.ui.dialogs.auth_dialogs import FirstRunDialog, LoginDialog
from servesync.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


class ServeSyncApp:
    """Owns the services and cycles between the sign-in screen and the main window."""

    def __init__(self, qt_app: QApplication, services: Services) -> None:
        self._qt = qt_app
        self._services = services
        self._window: MainWindow | None = None
        self._session: Session | None = None
        # "Match my computer": re-theme live when the OS switches light/dark.
        qt_app.styleHints().colorSchemeChanged.connect(lambda _scheme: self._follow_system())

    def start(self) -> bool:
        """Show first-run setup if needed, then sign-in. False if the user closed the window."""
        if self._services.setup.needs_setup():
            welcome = FirstRunDialog(self._services)
            if not welcome.exec():
                return False
            if welcome.session is not None:
                self._open_main(welcome.session)
                return True
        return self._sign_in()

    def _sign_in(self) -> bool:
        chosen: Language | None = None
        while True:
            login = LoginDialog(self._services)
            result = login.exec()
            if login.chosen_language is None:
                break
            # English/Español was picked: show the sign-in screen again in that language.
            chosen = login.chosen_language
            theme.apply_appearance(self._qt, self._services.settings.appearance())
            if result != LoginDialog.LANGUAGE_CHANGED:
                break
        if not result or login.session is None:
            return False
        if chosen is not None:  # the person just chose it, so it beats an older saved choice
            self._services.settings.set_appearance(login.session, language=chosen)
        self._open_main(login.session)
        return True

    def _open_main(self, session: Session, *, page: str = "") -> None:
        self._session = session
        theme.apply_appearance(self._qt, self._services.settings.appearance(session))
        events = AppEvents()
        ctx = AppContext(self._services, session, events)
        events.appearance_changed.connect(self._apply_appearance)
        window = MainWindow(ctx)
        window.signed_out.connect(self._after_sign_out)
        window.setWindowIcon(self._qt.windowIcon())
        window.resize(1360, 860)
        if page:
            window.navigate(page)
        window.show()
        self._window = window

    def _apply_appearance(self) -> None:
        before = current_language()
        theme.apply_appearance(self._qt, self._services.settings.appearance(self._session))
        if current_language() is not before and self._window is not None:
            # Every label was drawn in the old language; rebuild the window once the
            # current click has finished, keeping the person on the same page.
            QTimer.singleShot(0, self._rebuild_window)

    def _rebuild_window(self) -> None:
        old = self._window
        if old is None or self._session is None:
            return
        page = getattr(old.stack.currentWidget(), "key", "")
        geometry = old.saveGeometry()
        maximized = old.isMaximized()
        old.signed_out.disconnect()
        self._open_main(self._session, page=page)
        assert self._window is not None
        self._window.restoreGeometry(geometry)
        if maximized:
            self._window.showMaximized()
        old.hide()
        old.deleteLater()
        self._window.ctx.events.status_message.emit(
            tr("Language changed to {language}.", language=current_language().label)
        )

    def _follow_system(self) -> None:
        if theme.current_appearance().theme is Theme.SYSTEM:
            theme.apply_appearance(self._qt, theme.current_appearance())
            if self._window is not None:
                self._window.ctx.events.appearance_changed.emit()

    def _after_sign_out(self) -> None:
        if self._window is not None:
            self._window.deleteLater()
            self._window = None
        self._session = None
        theme.apply_appearance(self._qt, self._services.settings.appearance())
        if not self._sign_in():
            self._qt.quit()


def install_error_handler() -> None:
    """Last line of defense: log unexpected errors and keep the app running."""

    def handle(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("Unhandled error", exc_info=(exc_type, exc, tb))
        QMessageBox.warning(
            None,
            tr("Something went wrong"),
            tr("ServeSync hit an unexpected problem and recovered. Your data is safe.")
            + "\n"
            + tr("Details were saved to the log file."),
        )

    sys.excepthook = handle


def self_check(data_dir: Path | None = None) -> int:
    """
    ``ServeSync --check``: verify a computer can run ServeSync, without opening
    a window — the data file opens and upgrades, fonts and icons are bundled,
    and the stylesheet builds. Prints one line per check; exit code 0 = ready.
    """
    paths = AppPaths.resolve(data_dir)
    results: list[tuple[str, bool, str]] = []
    try:
        with DataStore.open(paths.database_file) as store:
            results.append(
                (
                    tr("Data file"),
                    True,
                    tr(
                        "{database_file} (schema v{query_value})",
                        database_file=paths.database_file,
                        query_value=store.db.query_value("PRAGMA user_version"),
                    ),
                )
            )
    except DataStoreError as error:
        results.append((tr("Data file"), False, error.message))
    body, heading = assets.load_fonts()
    results.append((tr("Fonts"), bool(body and heading), f"{body or 'missing'}, {heading or 'missing'}"))
    icons = list((assets.assets_dir() / "icons").glob("*.svg"))
    results.append((tr("Icons"), len(icons) >= 40, f"{len(icons)} found"))
    spanish = catalog(Language.SPANISH)
    results.append((tr("Translations"), len(spanish) > 500, f"{len(spanish)} Spanish messages"))
    try:
        theme.build_stylesheet(theme.LIGHT, 13.0)
        results.append((tr("Design system"), True, tr("stylesheet builds")))
    except Exception as error:
        results.append((tr("Design system"), False, str(error)))
    for name, ok, detail in results:
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
    ready = all(ok for _, ok, _ in results)
    print(f"{__app_name__} {__version__} is {'ready' if ready else 'NOT ready'} on this computer.")
    return 0 if ready else 1


def run(argv: list[str] | None = None, *, data_dir: Path | None = None) -> int:
    arguments = argv if argv is not None else sys.argv
    if "--check" in arguments:
        QApplication.instance() or QApplication([arguments[0] if arguments else __app_name__, "-platform", "offscreen"])
        return self_check(data_dir)
    qt_app = QApplication.instance() or QApplication(arguments)
    assert isinstance(qt_app, QApplication)
    qt_app.setApplicationName(__app_name__)
    qt_app.setApplicationVersion(__version__)
    qt_app.setOrganizationName(__app_name__)
    qt_app.setWindowIcon(QIcon(assets.logo_pixmap(256)))

    paths = AppPaths.resolve(data_dir)
    configure_logging(paths.log_dir)
    logger.info("Starting %s %s", __app_name__, __version__)

    body, heading = assets.load_fonts()
    theme.set_font_families(body, heading)
    try:
        store = DataStore.open(paths.database_file)
    except DataStoreError as error:
        theme.apply_theme(qt_app, Theme.LIGHT, 1.0)
        QMessageBox.critical(
            None,
            tr("{app} can't start", app=__app_name__),
            tr("{message}\n\nData folder: {folder}", message=error.message, folder=paths.data_dir),
        )
        return 1

    services = Services.create(store)
    theme.apply_appearance(qt_app, services.settings.appearance())
    install_error_handler()

    controller = ServeSyncApp(qt_app, services)
    try:
        if not controller.start():
            return 0
        return qt_app.exec()
    finally:
        store.close()
        logger.info("%s closed", __app_name__)
