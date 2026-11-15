"""
Main window: a conventional nonprofit layout adapted to a desktop app.

    [logo ServeSync]  | [ Ask a question or jump to a page ]    [ Call to action ]  [Account v]
    [ organization ]  |--------------------------------------------------------------------
     Page             |
     Page             |  page content
     ...              |
     Help             |

* Logo top-left; pages in a sidebar that keeps your place visible; one visually
  distinct call-to-action button in the upper-right corner (Add volunteer for
  leaders, Find a shift for volunteers).
* Responsive: if the window gets narrow (or text is enlarged), the sidebar
  shrinks to icons with tooltips and accessible names, so nothing is cut off.
* A thin marker slides to the current page (spring motion; instant with
  Reduce motion), so the change of place is easy to follow.
* Keyboard: Ctrl+1..7 pages, Ctrl+K Ask ServeSync, Ctrl+N call to action,
  Ctrl+F search, Ctrl+= / Ctrl+- / Ctrl+0 text size, F1 help.
* Feedback: confirmations appear as toasts (never stealing focus) and are
  spoken to screen readers; Help > Recent messages lists the last 30.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import Any

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QFont, QFontMetrics, QIcon, QKeySequence, QResizeEvent, QShortcut
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
from servesync.core.errors import ServeSyncError
from servesync.core.i18n import tr
from servesync.models import Theme
from servesync.models.preferences import MAX_FONT_SCALE, MIN_FONT_SCALE
from servesync.services import Permission
from servesync.ui import assets
from servesync.ui.context import AppContext
from servesync.ui.dialogs.assistant_dialog import AssistantDialog, Command
from servesync.ui.dialogs.auth_dialogs import ChangePasswordDialog
from servesync.ui.dialogs.help_dialog import TOPIC_TAB, HelpDialog, PageHelpDialog, RecentMessagesDialog
from servesync.ui.dialogs.volunteer_dialog import VolunteerDialog
from servesync.ui.feedback import Announcer, ToastHost
from servesync.ui.help_topics import LEADER_TOUR, VOLUNTEER_TOUR, TourStep
from servesync.ui.motion import DURATION_BASE, DURATION_FAST, animate, fade_in
from servesync.ui.pages.base import Page
from servesync.ui.pages.leader_pages import DashboardPage
from servesync.ui.pages.programs_page import ProgramsPage
from servesync.ui.pages.reports_page import ReportsPage
from servesync.ui.pages.shared_pages import CalendarPage, SettingsPage
from servesync.ui.pages.staffing_page import StaffingPage
from servesync.ui.pages.volunteer_pages import FindShiftsPage, HomePage, ProfilePage
from servesync.ui.pages.volunteers_page import VolunteersPage
from servesync.ui.theme import current_appearance, current_palette, current_scale
from servesync.ui.tour import TourGuide
from servesync.ui.widgets.common import guarded

logger = logging.getLogger(__name__)

#: The tour waits this long after sign-in, so the window has drawn before it appears.
TOUR_DELAY_MS = 400
#: Text-size steps for Ctrl+= and Ctrl+- (same steps as Settings).
TEXT_STEPS = (0.85, 1.0, 1.15, 1.3, 1.5, 1.75, 2.0)
#: Below this window width the sidebar shows icons only; it may take at most a quarter of the window.
SIDEBAR_LABELS_MIN_WINDOW = 1180
SIDEBAR_MAX_SHARE = 4
SIDEBAR_MIN_WIDTH = 232
#: From this text size up, the organization's name is left out of the sidebar (the window title has the page).
ORG_NAME_MAX_SCALE = 1.5


class MainWindow(QMainWindow):
    signed_out = Signal()

    def __init__(self, ctx: AppContext, *, offer_tour: bool = False) -> None:
        super().__init__()
        self.ctx = ctx
        ctx.navigate = self.navigate
        self._signing_out = False
        leader = ctx.session.is_leader
        organization = ctx.services.settings.organization_name()
        self.setWindowTitle(f"{__app_name__} - {organization}")
        self.setMinimumSize(1080, 700)

        page_types: list[type[Page]] = (
            [DashboardPage, VolunteersPage, ProgramsPage, CalendarPage, StaffingPage, ReportsPage, SettingsPage]
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
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_top_bar(leader))
        column.addWidget(self.stack, 1)
        row.addWidget(self._build_sidebar(organization))
        row.addLayout(column, 1)
        self.setCentralWidget(root)
        self._restyle_icons()
        self._build_menus()
        self._build_shortcuts()

        self.toasts = ToastHost(self, self.announcer)
        ctx.events.status_message.connect(self._confirm)
        ctx.events.announcement.connect(self.announcer.announce)
        ctx.events.appearance_changed.connect(self._restyle_icons)
        self.statusBar().showMessage(
            tr(
                ("Signed in as {username}. Press Ctrl+K to ask a question, or F1 for help."),
                username=ctx.session.username,
            ),
            10000,
        )
        self.navigate(next(iter(self.pages)))
        self._tour: TourGuide | None = None
        if offer_tour and not ctx.services.settings.tour_seen(ctx.session):
            QTimer.singleShot(TOUR_DELAY_MS, self.start_tour)  # once the window is on screen

    # ------------------------------------------------------------------ chrome

    def _build_sidebar(self, organization: str) -> QWidget:
        bar = QWidget()
        bar.setObjectName("Sidebar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        column = QVBoxLayout(bar)
        column.setContentsMargins(16, 16, 16, 16)
        column.setSpacing(4)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 16)
        heading.setSpacing(8)
        self.logo = QLabel()
        self.logo.setAccessibleName(tr("ServeSync logo"))
        heading.addWidget(self.logo)
        self.brand = QWidget()
        names = QVBoxLayout(self.brand)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        brand = QLabel(__app_name__)
        brand.setObjectName("Brand")
        org = QLabel(organization)
        org.setObjectName("OrgName")
        org.setWordWrap(True)
        self.org_name = org
        names.addWidget(brand)
        names.addWidget(org)
        heading.addWidget(self.brand, 1)
        column.addLayout(heading)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for page in self.pages.values():
            if page.key == "find":  # volunteers reach it through the call-to-action button
                continue
            button = self._nav_button(page.title)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, key=page.key: self.navigate(key))
            self.nav_group.addButton(button)
            self.nav_buttons[page.key] = button
            column.addWidget(button)
        column.addStretch(1)
        self.help_button = self._nav_button(tr("Help"))
        self.help_button.setToolTip(tr("Help (F1)"))
        self.help_button.clicked.connect(lambda _checked=False: self.show_help())
        column.addWidget(self.help_button)

        self.sidebar = bar
        self.indicator = QWidget(bar)
        self.indicator.setObjectName("NavIndicator")
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.indicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.indicator.hide()
        return bar

    @staticmethod
    def _nav_button(title: str) -> QPushButton:
        button = QPushButton(title)
        button.setProperty("nav", True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAccessibleName(title)
        button.setToolTip(title)
        return button

    def _build_top_bar(self, leader: bool) -> QWidget:
        bar = QWidget()
        bar.setObjectName("TopBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row = QHBoxLayout(bar)
        row.setContentsMargins(32, 8, 32, 8)
        row.setSpacing(16)

        self.ask_button = QPushButton()
        self.ask_button.setObjectName("AskButton")
        self.ask_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ask_button.setAccessibleName(tr("Ask ServeSync"))
        self.ask_button.setToolTip(tr("Ask a question or jump to a page (Ctrl+K)"))
        self.ask_button.clicked.connect(self.show_assistant)
        row.addWidget(self.ask_button, 3)
        row.addStretch(1)

        self.cta = QPushButton(tr("Add volunteer") if leader else tr("Find a shift"))
        self.cta.setObjectName("CallToAction")
        self.cta.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cta.setToolTip(tr("Register a new volunteer (Ctrl+N)") if leader else tr("Browse open shifts (Ctrl+N)"))
        self.cta.clicked.connect(self._call_to_action)
        row.addWidget(self.cta)

        self.page_help_button = QToolButton()
        self.page_help_button.setObjectName("PageHelp")
        self.page_help_button.setText("?")
        self.page_help_button.setAccessibleName(tr("Help for this page"))
        self.page_help_button.setToolTip(tr("Help for this page"))
        self.page_help_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.page_help_button.clicked.connect(self.show_page_help)
        row.addWidget(self.page_help_button)

        self.account = QToolButton()
        self.account.setObjectName("UserMenu")
        self.account.setText(self.ctx.session.username)  # the stylesheet draws the menu chevron
        self.account.setAccessibleName(tr("Account menu for {username}", username=self.ctx.session.username))
        self.account.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.account)
        menu.addAction(tr("Signed in as {label}", label=self.ctx.session.role.label)).setEnabled(False)
        menu.addSeparator()
        menu.addAction(tr("Change password..."), self._change_password)
        menu.addAction(tr("Help"), self.show_help)
        menu.addAction(tr("Take the tour"), self.start_tour)
        menu.addSeparator()
        menu.addAction(tr("Sign out"), self.sign_out)
        self.account.setMenu(menu)
        row.addWidget(self.account)
        return bar

    def _restyle_icons(self) -> None:
        """Recolor and resize icons for the current theme and text size."""
        palette = current_palette()
        color = palette.sidebar_text
        size = round(18 * current_scale())
        self.logo.setPixmap(assets.logo_pixmap(palette.brand, 32))
        # The current page's icon turns indigo along with its label (the "On" state of a checked button).
        self._nav_icons = {
            key: assets.two_state_icon(self.pages[key].icon_name, color, palette.sidebar_accent, size)
            for key in self.nav_buttons
        }
        for button in (*self.nav_buttons.values(), self.help_button):
            button.setIconSize(QSize(size, size))
        self.help_button.setIcon(assets.icon("help", color, size))
        self.cta.setIcon(assets.icon("user-plus" if self.ctx.session.is_leader else "search", palette.on_cta, size))
        self.cta.setIconSize(QSize(size, size))
        self.ask_button.setIcon(assets.icon("search", palette.text_muted, size))
        self.ask_button.setIconSize(QSize(size, size))
        self._fit_navigation()
        QTimer.singleShot(0, lambda: self._move_indicator(animated=False))

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu(tr("&File"))
        sign_out = QAction(tr("Sign out"), self)
        sign_out.triggered.connect(self.sign_out)
        file_menu.addAction(sign_out)
        quit_action = QAction(tr("Quit"), self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)
        go_menu = self.menuBar().addMenu(tr("&Go"))
        for index, page in enumerate(self.pages.values(), start=1):
            action = QAction(page.title, self)
            action.setShortcut(QKeySequence(f"Ctrl+{index}"))
            action.triggered.connect(lambda _checked=False, key=page.key: self.navigate(key))
            go_menu.addAction(action)
        view_menu = self.menuBar().addMenu(tr("&View"))
        for text, keys, step in (
            (tr("Larger text"), ("Ctrl++", "Ctrl+="), 1),  # "=" too, for keyboards where "+" needs Shift
            (tr("Smaller text"), ("Ctrl+-",), -1),
        ):
            action = QAction(text, self)
            action.setShortcuts([QKeySequence(key) for key in keys])
            action.triggered.connect(lambda _checked=False, step=step: self.change_text_size(step))
            view_menu.addAction(action)
        reset = QAction(tr("Normal text size"), self)
        reset.setShortcut(QKeySequence("Ctrl+0"))
        reset.triggered.connect(lambda: self.change_text_size(0))
        view_menu.addAction(reset)
        contrast = QAction(tr("High contrast on/off"), self)
        contrast.setShortcut(QKeySequence("Ctrl+Shift+H"))
        contrast.triggered.connect(self.toggle_high_contrast)
        view_menu.addAction(contrast)
        help_menu = self.menuBar().addMenu(tr("&Help"))
        ask = QAction(tr("Ask ServeSync"), self)
        ask.setShortcut(QKeySequence("Ctrl+K"))
        ask.triggered.connect(self.show_assistant)
        help_menu.addAction(ask)
        guide = QAction(tr("Getting started"), self)
        guide.setShortcut(QKeySequence(Qt.Key.Key_F1))
        guide.triggered.connect(self.show_help)
        help_menu.addAction(guide)
        shortcuts = QAction(tr("Keyboard shortcuts"), self)
        shortcuts.triggered.connect(lambda: self.show_help(tab=1))
        help_menu.addAction(shortcuts)
        recent = QAction(tr("Recent messages"), self)
        recent.triggered.connect(self.show_recent_messages)
        help_menu.addAction(recent)
        topic = QAction(tr("How ServeSync addresses the topic"), self)
        topic.triggered.connect(lambda: self.show_help(tab=TOPIC_TAB))
        help_menu.addAction(topic)
        tour = QAction(tr("Take the tour"), self)
        tour.triggered.connect(self.start_tour)
        help_menu.addAction(tour)
        about = QAction(tr("About {app}", app=__app_name__), self)
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
        if self.stack.currentWidget() is not page:
            fade_in(page, DURATION_FAST)
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
        self.announcer.announce(tr("{title} page", title=page.title))

    @guarded
    def _call_to_action(self) -> None:
        if self.ctx.session.can(Permission.MANAGE_VOLUNTEERS):
            dialog = VolunteerDialog(self.ctx, None, self)
            if dialog.exec() and dialog.saved is not None:
                self.ctx.changed(
                    tr(
                        ("Added {full_name}. Approve them on the Volunteers page when they're ready."),
                        full_name=dialog.saved.full_name,
                    )
                )
                self.navigate("volunteers")
        else:
            self.navigate("find")

    def _focus_search(self) -> None:
        page = self.stack.currentWidget()
        if isinstance(page, Page) and not page.focus_search():
            self.statusBar().showMessage(tr("This page has no search box."), 3000)

    def show_help(self, tab: int = 0) -> None:
        HelpDialog(self.ctx.session.role, self, start_tab=tab).exec()

    def show_page_help(self) -> None:
        page = self.stack.currentWidget()
        key = page.key if isinstance(page, Page) else ""
        PageHelpDialog(key, self.ctx.session.role, self).exec()

    def start_tour(self) -> None:
        """Show the short tour for this person's role (also from Help > Take the tour)."""
        if self._tour is not None:
            return
        steps = LEADER_TOUR if self.ctx.session.is_leader else VOLUNTEER_TOUR
        self._tour = TourGuide(
            self,
            [step for step in steps if step.page in self.pages],
            go_to=self.navigate,
            target_for=self._tour_target,
            announce=self.announcer.announce,
            on_done=self._tour_done,
        )
        self._tour.start()

    def _tour_target(self, step: TourStep) -> QWidget | None:
        if step.target == "ask":
            return self.ask_button
        if step.target == "cta":
            return self.cta
        if step.target == "help":
            return self.page_help_button
        return self.nav_buttons.get(step.page)

    def _tour_done(self) -> None:
        self._tour = None
        try:
            self.ctx.services.settings.set_tour_seen(self.ctx.session)
        except ServeSyncError:  # never block the app over a preference
            logger.exception("Could not save that the tour was seen")

    def show_recent_messages(self) -> None:
        RecentMessagesDialog(list(self.announcer.history), self).exec()

    def show_assistant(self) -> AssistantDialog:
        dialog = AssistantDialog(self.ctx, self.commands(), self)
        dialog.open()
        return dialog

    def commands(self) -> list[Command]:
        """Everything Ask ServeSync can jump to, with the same shortcuts as the menus."""
        items = [
            Command(tr("Go to {title}", title=page.title), partial(self.navigate, page.key), f"Ctrl+{index}")
            for index, page in enumerate(self.pages.values(), start=1)
        ]
        items += [
            Command(self.cta.text(), self._call_to_action, "Ctrl+N"),
            Command(tr("Larger text"), lambda: self.change_text_size(1), "Ctrl+="),
            Command(tr("Smaller text"), lambda: self.change_text_size(-1), "Ctrl+-"),
            Command(tr("High contrast on/off"), self.toggle_high_contrast, "Ctrl+Shift+H"),
            Command(tr("Comfort and accessibility settings"), lambda: self.navigate("settings")),
            Command(tr("Keyboard shortcuts"), lambda: self.show_help(tab=1)),
            Command(tr("Getting started help"), self.show_help, "F1"),
            Command(tr("Help for this page"), self.show_page_help),
            Command(tr("How ServeSync addresses the topic"), lambda: self.show_help(tab=TOPIC_TAB)),
            Command(tr("Take the tour"), self.start_tour),
            Command(tr("Recent messages"), self.show_recent_messages),
            Command(tr("Change password"), self._change_password),
            Command(tr("Sign out"), self.sign_out),
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
            self.announcer.announce(
                tr("Text is already at its largest size") if step > 0 else tr("Text is already at its smallest size")
            )
            return
        self.ctx.services.settings.set_appearance(self.ctx.session, font_scale=target)
        self.ctx.events.appearance_changed.emit()
        self.announcer.announce(tr("Text size {target:.0%}", target=target))

    @guarded
    def toggle_high_contrast(self) -> None:
        on = current_appearance().theme is not Theme.HIGH_CONTRAST
        self.ctx.services.settings.set_appearance(self.ctx.session, theme=Theme.HIGH_CONTRAST if on else Theme.SYSTEM)
        self.ctx.events.appearance_changed.emit()
        self.announcer.announce(tr("High contrast on") if on else tr("High contrast off"))

    @guarded
    def _change_password(self) -> None:
        if ChangePasswordDialog(self.ctx.services, self.ctx.session, self).exec():
            self.statusBar().showMessage(tr("Password changed."), 5000)

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
        target = QRect(geometry.left() - 8, geometry.top() + 8, 4, max(geometry.height() - 16, 12))
        self.indicator.show()
        self.indicator.raise_()
        if animated and self.indicator.geometry().width() > 0:
            animate(self.indicator, "geometry", target, duration=DURATION_BASE)
        else:
            self.indicator.setGeometry(target)

    def _fit_navigation(self) -> None:
        """Labels when they fit (calm, scannable); icons with tooltips when space is tight."""
        if not hasattr(self, "nav_buttons"):
            return
        icon_width = self.help_button.iconSize().width()
        bold = QFont(self.font())  # the current page's label is bold, so measure that width
        bold.setBold(True)
        labels_width = max(
            QFontMetrics(bold).horizontalAdvance(f"  {self.pages[key].title}") for key in self.nav_buttons
        )
        width = max(SIDEBAR_MIN_WIDTH, labels_width + icon_width + 88)  # padding, icon gap, and margins
        compact = self.width() < max(SIDEBAR_LABELS_MIN_WINDOW, width * SIDEBAR_MAX_SHARE)
        for key, button in self.nav_buttons.items():
            button.setText("" if compact else f"  {self.pages[key].title}")  # spaces: Qt styles have no icon gap
            button.setIcon(getattr(self, "_nav_icons", {}).get(key, QIcon()))
        self.help_button.setText("" if compact else f"  {tr('Help')}")
        self.brand.setVisible(not compact)
        self.org_name.setVisible(current_scale() < ORG_NAME_MAX_SCALE)  # no room beside the logo at large text
        self.sidebar.setFixedWidth(icon_width + 64 if compact else width)
        self._fit_ask_button(self.sidebar.width())

    def _fit_ask_button(self, sidebar_width: int) -> None:
        """The full invitation when it fits; the single word when the header is tight."""
        full = tr("Ask a question or jump to a page")
        room = self.width() - sidebar_width - self.cta.sizeHint().width() - self.account.sizeHint().width() - 88
        needed = self.ask_button.fontMetrics().horizontalAdvance(full) + self.ask_button.iconSize().width() + 48
        self.ask_button.setText(full if needed <= room * 3 // 4 else tr("Ask"))
