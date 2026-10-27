"""
Main window: a conventional nonprofit layout adapted to a desktop app.

    [logo  ServeSync / organization]          Nav  Nav  Nav  Nav  Nav  [ Call to action ]  [Account v]
    -------------------------------------------------------------------------------------------------
    page content

* Logo top-left; main navigation top-right; one visually distinct
  call-to-action button in the upper-right corner (Add volunteer for leaders,
  Find a shift for volunteers).
* Responsive: if the window gets narrow (or text is enlarged), navigation
  switches to icons with tooltips and accessible names, so nothing is cut off.
* A thin marker slides under the current page (spring motion; instant with
  Reduce motion), so the change of place is easy to follow.
* Keyboard: Ctrl+1..6 pages, Ctrl+K Ask ServeSync, Ctrl+N call to action,
  Ctrl+F search, Ctrl+= / Ctrl+- / Ctrl+0 text size, F1 help.
* Feedback: confirmations appear as toasts (never stealing focus) and are
  spoken to screen readers; Help > Recent messages lists the last 30.
"""

from __future__ import annotations

from functools import partial
from typing import Any

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from servesync import __app_name__
from servesync.models import Theme
from servesync.models.preferences import MAX_FONT_SCALE, MIN_FONT_SCALE
from servesync.services import Permission
from servesync.ui import assets
from servesync.ui.context import AppContext
from servesync.ui.dialogs.assistant_dialog import AssistantDialog, Command
from servesync.ui.dialogs.auth_dialogs import ChangePasswordDialog
from servesync.ui.dialogs.help_dialog import HelpDialog, RecentMessagesDialog
from servesync.ui.dialogs.volunteer_dialog import VolunteerDialog
from servesync.ui.feedback import Announcer, ToastHost
from servesync.ui.motion import DURATION_BASE, animate
from servesync.ui.pages.base import Page
from servesync.ui.pages.leader_pages import DashboardPage
from servesync.ui.pages.programs_page import ProgramsPage
from servesync.ui.pages.reports_page import ReportsPage
from servesync.ui.pages.shared_pages import CalendarPage, SettingsPage
from servesync.ui.pages.volunteer_pages import FindShiftsPage, HomePage, ProfilePage
from servesync.ui.pages.volunteers_page import VolunteersPage
from servesync.ui.theme import current_appearance, current_palette, current_scale
from servesync.ui.widgets.common import guarded

#: Text-size steps for Ctrl+= and Ctrl+- (same steps as Settings).
TEXT_STEPS = (0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)


class MainWindow(QMainWindow):
    signed_out = Signal()

    def __init__(self, ctx: AppContext) -> None:
        super().__init__()
        self.ctx = ctx
        ctx.navigate = self.navigate
        self._signing_out = False
        leader = ctx.session.is_leader
        organization = ctx.services.settings.organization_name()
        self.setWindowTitle(f"{__app_name__} - {organization}")
        self.setMinimumSize(1080, 700)

        page_types: list[type[Page]] = (
            [DashboardPage, VolunteersPage, ProgramsPage, CalendarPage, ReportsPage, SettingsPage]
            if leader
            else [HomePage, FindShiftsPage, CalendarPage, ReportsPage, ProfilePage, SettingsPage]
        )
        self.announcer = Announcer(self)
        self.pages: dict[str, Page] = {}
        self.stack = QStackedWidget()
        for page_type in page_types:
            page = page_type(ctx)
            self.pages[page.key] = page
            self.stack.addWidget(page)

        root = QWidget()
        column = QVBoxLayout(root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_top_bar(organization, leader))
        column.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self._build_menus()
        self._build_shortcuts()

        self.toasts = ToastHost(self, self.announcer)
        ctx.events.status_message.connect(self._confirm)
        ctx.events.announcement.connect(self.announcer.announce)
        ctx.events.appearance_changed.connect(self._restyle_icons)
        self.statusBar().showMessage(
            f"Signed in as {ctx.session.username}. Press Ctrl+K to ask a question, or F1 for help.", 10000
        )
        self.navigate(next(iter(self.pages)))

    # ------------------------------------------------------------------ chrome

    def _build_top_bar(self, organization: str, leader: bool) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(20, 10, 20, 10)
        row.setSpacing(6)

        logo = QLabel()
        logo.setPixmap(assets.logo_pixmap(38))
        logo.setAccessibleName("ServeSync logo")
        row.addWidget(logo)
        self.brand = QWidget()
        names = QVBoxLayout(self.brand)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        brand = QLabel(__app_name__)
        brand.setObjectName("Brand")
        org = QLabel(organization)
        org.setObjectName("OrgName")
        names.addWidget(brand)
        names.addWidget(org)
        row.addWidget(self.brand)
        row.addStretch(1)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for page in self.pages.values():
            if page.key == "find":  # volunteers reach it through the call-to-action button
                continue
            button = QPushButton(page.title)
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(page.title)
            button.setToolTip(page.title)
            button.clicked.connect(lambda _checked=False, key=page.key: self.navigate(key))
            self.nav_group.addButton(button)
            self.nav_buttons[page.key] = button
            row.addWidget(button)
        row.addSpacing(10)

        self.ask_button = QPushButton("Ask")
        self.ask_button.setObjectName("AskButton")
        self.ask_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ask_button.setAccessibleName("Ask ServeSync")
        self.ask_button.setToolTip("Ask a question or jump to a page (Ctrl+K)")
        self.ask_button.clicked.connect(self.show_assistant)
        row.addWidget(self.ask_button)
        row.addSpacing(6)

        self.cta = QPushButton("Add volunteer" if leader else "Find a shift")
        self.cta.setObjectName("CallToAction")
        self.cta.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cta.setToolTip("Register a new volunteer (Ctrl+N)" if leader else "Browse open shifts (Ctrl+N)")
        self.cta.clicked.connect(self._call_to_action)
        row.addWidget(self.cta)
        row.addSpacing(6)

        self.account = QToolButton()
        self.account.setObjectName("UserMenu")
        self.account.setText(f"{self.ctx.session.username}  ▾")
        self.account.setAccessibleName(f"Account menu for {self.ctx.session.username}")
        self.account.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.account)
        menu.addAction(f"Signed in as {self.ctx.session.role.label}").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Change password...", self._change_password)
        menu.addAction("Help", self.show_help)
        menu.addSeparator()
        menu.addAction("Sign out", self.sign_out)
        self.account.setMenu(menu)
        row.addWidget(self.account)
        self.top_bar = bar
        self.indicator = QWidget(bar)
        self.indicator.setObjectName("NavIndicator")
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.indicator.hide()
        self._restyle_icons()
        return bar

    def _restyle_icons(self) -> None:
        """Recolor and resize icons for the current theme and text size."""
        color = current_palette().topbar_text
        size = round(18 * current_scale())
        self._nav_icons = {key: assets.icon(self.pages[key].icon_name, color, size) for key in self.nav_buttons}
        for button in self.nav_buttons.values():
            button.setIconSize(QSize(size, size))
        self.cta.setIcon(
            assets.icon("user-plus" if self.ctx.session.is_leader else "search", current_palette().on_cta, size)
        )
        self.cta.setIconSize(QSize(size, size))
        self.ask_button.setIcon(assets.icon("sparkles", current_palette().primary, size))
        self.ask_button.setIconSize(QSize(size, size))
        self._fit_navigation()
        QTimer.singleShot(0, lambda: self._move_indicator(animated=False))

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        sign_out = QAction("Sign out", self)
        sign_out.triggered.connect(self.sign_out)
        file_menu.addAction(sign_out)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        go_menu = self.menuBar().addMenu("&Go")
        for index, page in enumerate(self.pages.values(), start=1):
            action = QAction(page.title, self)
            action.setShortcut(QKeySequence(f"Ctrl+{index}"))
            action.triggered.connect(lambda _checked=False, key=page.key: self.navigate(key))
            go_menu.addAction(action)
        view_menu = self.menuBar().addMenu("&View")
        for text, keys, step in (
            ("Larger text", ("Ctrl++", "Ctrl+="), 1),  # "=" too, for keyboards where "+" needs Shift
            ("Smaller text", ("Ctrl+-",), -1),
        ):
            action = QAction(text, self)
            action.setShortcuts([QKeySequence(key) for key in keys])
            action.triggered.connect(lambda _checked=False, step=step: self.change_text_size(step))
            view_menu.addAction(action)
        reset = QAction("Normal text size", self)
        reset.setShortcut(QKeySequence("Ctrl+0"))
        reset.triggered.connect(lambda: self.change_text_size(0))
        view_menu.addAction(reset)
        contrast = QAction("High contrast on/off", self)
        contrast.setShortcut(QKeySequence("Ctrl+Shift+H"))
        contrast.triggered.connect(self.toggle_high_contrast)
        view_menu.addAction(contrast)
        help_menu = self.menuBar().addMenu("&Help")
        ask = QAction("Ask ServeSync", self)
        ask.setShortcut(QKeySequence("Ctrl+K"))
        ask.triggered.connect(self.show_assistant)
        help_menu.addAction(ask)
        guide = QAction("Getting started", self)
        guide.setShortcut(QKeySequence(Qt.Key.Key_F1))
        guide.triggered.connect(self.show_help)
        help_menu.addAction(guide)
        shortcuts = QAction("Keyboard shortcuts", self)
        shortcuts.triggered.connect(lambda: self.show_help(tab=1))
        help_menu.addAction(shortcuts)
        recent = QAction("Recent messages", self)
        recent.triggered.connect(self.show_recent_messages)
        help_menu.addAction(recent)
        about = QAction(f"About {__app_name__}", self)
        about.triggered.connect(lambda: self.show_help(tab=2))
        help_menu.addAction(about)

    def _build_shortcuts(self) -> None:
        call_to_action = QShortcut(QKeySequence("Ctrl+N"), self)
        call_to_action.activated.connect(self._call_to_action)
        find = QShortcut(QKeySequence(QKeySequence.StandardKey.Find), self)
        find.activated.connect(self._focus_search)

    # -------------------------------------------------------------- behavior

    def navigate(self, key: str, **options: Any) -> None:
        page = self.pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        button = self.nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        else:  # a page reached from the call-to-action: no tab is highlighted
            self.nav_group.setExclusive(False)
            for other in self.nav_buttons.values():
                other.setChecked(False)
            self.nav_group.setExclusive(True)
        page.setFocus(Qt.FocusReason.OtherFocusReason)
        page.apply_options(**options)
        if options:
            page.reload()
        self.setWindowTitle(f"{page.title} - {__app_name__}")
        self._move_indicator(animated=True)
        self.announcer.announce(f"{page.title} page")

    @guarded
    def _call_to_action(self) -> None:
        if self.ctx.session.can(Permission.MANAGE_VOLUNTEERS):
            dialog = VolunteerDialog(self.ctx, None, self)
            if dialog.exec() and dialog.saved is not None:
                self.ctx.changed(
                    f"Added {dialog.saved.full_name}. Approve them on the Volunteers page when they're ready."
                )
                self.navigate("volunteers")
        else:
            self.navigate("find")

    def _focus_search(self) -> None:
        page = self.stack.currentWidget()
        if isinstance(page, Page) and not page.focus_search():
            self.statusBar().showMessage("This page has no search box.", 3000)

    def show_help(self, tab: int = 0) -> None:
        HelpDialog(self.ctx.session.role, self, start_tab=tab).exec()

    def show_recent_messages(self) -> None:
        RecentMessagesDialog(list(self.announcer.history), self).exec()

    def show_assistant(self) -> AssistantDialog:
        dialog = AssistantDialog(self.ctx, self.commands(), self)
        dialog.open()
        return dialog

    def commands(self) -> list[Command]:
        """Everything Ask ServeSync can jump to, with the same shortcuts as the menus."""
        items = [
            Command(f"Go to {page.title}", partial(self.navigate, page.key), f"Ctrl+{index}")
            for index, page in enumerate(self.pages.values(), start=1)
        ]
        items += [
            Command(self.cta.text(), self._call_to_action, "Ctrl+N"),
            Command("Larger text", lambda: self.change_text_size(1), "Ctrl+="),
            Command("Smaller text", lambda: self.change_text_size(-1), "Ctrl+-"),
            Command("High contrast on/off", self.toggle_high_contrast, "Ctrl+Shift+H"),
            Command("Comfort and accessibility settings", lambda: self.navigate("settings")),
            Command("Keyboard shortcuts", lambda: self.show_help(tab=1)),
            Command("Getting started help", self.show_help, "F1"),
            Command("Recent messages", self.show_recent_messages),
            Command("Change password", self._change_password),
            Command("Sign out", self.sign_out),
        ]
        return items

    def _confirm(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)
        self.toasts.show_message(message)

    @guarded
    def change_text_size(self, step: int) -> None:
        """Ctrl+= / Ctrl+- move one step; 0 resets to 100%. Saved to this person's settings."""
        current = current_appearance().font_scale
        if step == 0:
            target = 1.0
        else:
            index = min(range(len(TEXT_STEPS)), key=lambda i: abs(TEXT_STEPS[i] - current))
            target = TEXT_STEPS[max(0, min(index + step, len(TEXT_STEPS) - 1))]
        target = max(MIN_FONT_SCALE, min(target, MAX_FONT_SCALE))
        if target == current:
            self.announcer.announce("Text is already at its " + ("largest" if step > 0 else "smallest") + " size")
            return
        self.ctx.services.settings.set_appearance(self.ctx.session, font_scale=target)
        self.ctx.events.appearance_changed.emit()
        self.announcer.announce(f"Text size {target:.0%}")

    @guarded
    def toggle_high_contrast(self) -> None:
        on = current_appearance().theme is not Theme.HIGH_CONTRAST
        self.ctx.services.settings.set_appearance(self.ctx.session, theme=Theme.HIGH_CONTRAST if on else Theme.SYSTEM)
        self.ctx.events.appearance_changed.emit()
        self.announcer.announce("High contrast on" if on else "High contrast off")

    @guarded
    def _change_password(self) -> None:
        if ChangePasswordDialog(self.ctx.services, self.ctx.session, self).exec():
            self.statusBar().showMessage("Password changed.", 5000)

    def sign_out(self) -> None:
        self._signing_out = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        super().closeEvent(event)
        if self._signing_out:
            self.signed_out.emit()

    # ------------------------------------------------------------ responsive

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit_navigation()
        self._move_indicator(animated=False)

    def _move_indicator(self, *, animated: bool) -> None:
        """Slide the marker under the current page's tab (hidden for pages without a tab)."""
        if not hasattr(self, "indicator"):
            return
        page = self.stack.currentWidget()
        button = self.nav_buttons.get(page.key) if isinstance(page, Page) else None
        if button is None or not button.isVisible():
            self.indicator.hide()
            return
        geometry = button.geometry()
        target = QRect(geometry.left() + 10, self.top_bar.height() - 3, max(geometry.width() - 20, 12), 3)
        self.indicator.show()
        self.indicator.raise_()
        if animated and self.indicator.geometry().width() > 0:
            animate(self.indicator, "geometry", target, duration=DURATION_BASE)
        else:
            self.indicator.setGeometry(target)

    def _fit_navigation(self) -> None:
        """Text labels when they fit (calm, scannable); icons with tooltips when space is tight."""
        if not hasattr(self, "nav_buttons"):
            return
        labels_width = sum(
            button.fontMetrics().horizontalAdvance(self.pages[key].title) + 30  # text + padding
            for key, button in self.nav_buttons.items()
        )
        reserved = (
            40  # window margins
            + 38
            + 12
            + self.brand.sizeHint().width()  # logo and names
            + self.ask_button.sizeHint().width()
            + self.cta.sizeHint().width()
            + self.account.sizeHint().width()
            + 6 * (len(self.nav_buttons) + 4)  # spacing between items
            + 24  # breathing room
        )
        compact = self.width() < labels_width + reserved
        for key, button in self.nav_buttons.items():
            button.setText("" if compact else self.pages[key].title)
            button.setIcon(getattr(self, "_nav_icons", {}).get(key, QIcon()) if compact else QIcon())
