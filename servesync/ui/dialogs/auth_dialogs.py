"""Sign-in, first-launch setup, and password change dialogs."""

from __future__ import annotations

from collections.abc import Callable
from html import escape

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from servesync.core.errors import AuthenticationError, ServeSyncError, ValidationError
from servesync.core.i18n import Language, current_language, tr, tr_n
from servesync.data.seed import DEMO_ORGANIZATION_NAME, DEMO_PASSWORD
from servesync.services import Services, Session
from servesync.ui import assets
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import BusyCursor, Panel, make_button, make_label
from servesync.ui.widgets.forms import FormDialog
from servesync.ui.widgets.visuals import NetworkGlobe


def _password_field(placeholder: str = "") -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setPlaceholderText(placeholder)
    field.setMaxLength(128)
    return field


def headline(plain: str, accent: str) -> QLabel:
    """
    A large, light page heading whose last words are picked out in the accent
    blue ("Hello *again.*"). The two parts are separate messages so each
    language can phrase them naturally; the accessible name is the whole line.
    """
    color = current_palette().primary
    label = make_label(f'{escape(plain)} <span style="color: {color};">{escape(accent)}</span>', "display")
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setWordWrap(True)
    label.setAccessibleName(f"{plain} {accent}")
    return label


def _rule(text: str) -> QWidget:
    """A small monospaced label followed by a hairline: "or continue with ────────"."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 8, 0, 0)
    row.setSpacing(16)
    row.addWidget(make_label(text, "eyebrow"))
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setProperty("callout", True)
    line.setFixedHeight(1)
    row.addWidget(line, 1)
    return holder


def _wordmark() -> QWidget:
    """The logo and the ServeSync name in blue, top left, as on a website's header."""
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    logo = QLabel()
    logo.setPixmap(assets.logo_pixmap(current_palette().brand, 28))
    logo.setAccessibleName(tr("ServeSync logo"))
    row.addWidget(logo)
    brand = QLabel("ServeSync")
    brand.setObjectName("Brand")
    row.addWidget(brand)
    return holder


def _brand_panel(organization: str, mission: str, figure: int | None = None) -> QFrame:
    """
    The right half of the welcome screens: the organization's name, a turning
    globe of connected points (neighbors linked to neighbors), one big figure,
    and the mission. The picture is decorative; everything it means is in text.
    """
    panel = QFrame()
    panel.setProperty("panel", True)
    panel.setMinimumWidth(340)
    column = QVBoxLayout(panel)
    column.setContentsMargins(40, 40, 40, 32)
    column.setSpacing(8)
    org = make_label(organization, "eyebrow", wrap=True)
    org.setObjectName("OrgName")
    column.addWidget(org)
    column.addWidget(NetworkGlobe(), 1)
    if figure is not None:
        number = QHBoxLayout()
        number.setSpacing(12)
        number.addWidget(make_label(str(figure), "display"), 0, Qt.AlignmentFlag.AlignBottom)
        word = make_label(tr_n("volunteer", "volunteers", figure), "accent")
        number.addWidget(word, 0, Qt.AlignmentFlag.AlignBottom)
        number.addStretch(1)
        column.addLayout(number)
    if mission:
        statement = make_label(mission, "mission", wrap=True)
        statement.setAccessibleName(tr("Our mission: {mission}", mission=mission))
        column.addWidget(statement)
    column.addSpacing(8)
    column.addWidget(make_label(tr("Volunteer management for nonprofits"), "eyebrow", wrap=True))
    return panel


def _scrolling(content: QWidget) -> QScrollArea:
    """Let a form scroll rather than squeeze its fields when the window is small or the text is large."""
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(content)
    return area


def _stacked_field(label_text: str, field: QWidget) -> QWidget:
    """A label above its field, the field drawn as a single underline."""
    holder = QWidget()
    column = QVBoxLayout(holder)
    column.setContentsMargins(0, 0, 0, 0)
    column.setSpacing(4)
    label = QLabel(label_text)
    label.setBuddy(field)
    field.setAccessibleName(label_text.replace("&", ""))
    column.addWidget(label)
    column.addWidget(field)
    return holder


def language_switch(on_choose: Callable[[Language], None]) -> QWidget:
    """
    English | Español, each written in its own language so anyone can find
    theirs — even when the screen is in a language they can't read.
    """
    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(0)
    row.addStretch(1)
    group = QButtonGroup(holder)
    members = list(Language)
    for index, language in enumerate(members):
        button = QPushButton(language.label)
        button.setCheckable(True)
        button.setChecked(language is current_language())
        button.setProperty("segment", True)
        button.setProperty("first", index == 0)
        button.setProperty("last", index == len(members) - 1)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setAccessibleName({"en": "Language: English", "es": "Idioma: Español"}[language.value])
        button.clicked.connect(lambda _checked=False, chosen=language: on_choose(chosen))
        group.addButton(button, index)
        row.addWidget(button)
    return holder


class LoginDialog(QDialog):
    """Sign in. Shows demo accounts only when the demo organization is loaded."""

    #: ``exec()`` result when the person switched language (the app reopens the dialog).
    LANGUAGE_CHANGED = 2

    def __init__(self, services: Services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self.session: Session | None = None
        self.chosen_language: Language | None = None
        organization = services.settings.organization_name()
        self.setWindowTitle(tr("Sign in - {organization}", organization=organization))
        self.setMinimumSize(960, 640)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        form_side = QWidget()
        column = QVBoxLayout(form_side)
        column.setContentsMargins(48, 32, 48, 32)
        column.setSpacing(16)
        top = QHBoxLayout()
        top.addWidget(_wordmark())
        top.addStretch(1)
        top.addWidget(language_switch(self._choose_language))
        column.addLayout(top)
        column.addSpacing(24)
        column.addWidget(make_label(tr("Sign in"), "eyebrow"))
        column.addWidget(headline(tr("Hello"), tr("again.")))
        column.addWidget(
            make_label(tr("Use the username and password your coordinator gave you."), "subtitle", wrap=True)
        )
        self.error = make_label("", "banner-error", wrap=True)
        self.error.hide()
        column.addWidget(self.error)

        self.username = QLineEdit()
        self.username.setPlaceholderText(tr("for example, jordan.rivera"))
        self.username.setMaxLength(30)
        self.password = _password_field()
        column.addWidget(_stacked_field(tr("&Username"), self.username))
        column.addWidget(_stacked_field(tr("&Password"), self.password))

        self.sign_in_button = make_button(tr("Sign in"), kind="primary", on_click=self._sign_in)
        self.sign_in_button.setDefault(True)
        column.addWidget(self.sign_in_button)
        column.addWidget(_rule(tr("New here?")))
        self.apply_button = make_button(tr("Become a volunteer"), on_click=self._apply)
        column.addWidget(self.apply_button)

        if organization == DEMO_ORGANIZATION_NAME:
            column.addWidget(_rule(tr("Demo accounts")))
            column.addWidget(
                make_label(
                    tr(
                        (
                            "Leaders: admin, coordinator\nVolunteers: jordan.rivera, "
                            "priya.patel\nPassword for all: {DEMO_PASSWORD}"
                        ),
                        DEMO_PASSWORD=DEMO_PASSWORD,
                    ),
                    "muted",
                    wrap=True,
                    selectable=True,
                )
            )
        column.addStretch(1)
        row.addWidget(_scrolling(form_side), 1)
        row.addWidget(
            _brand_panel(
                organization,
                services.settings.mission_statement(),
                services.settings.active_volunteer_count(),
            ),
            1,
        )
        self.username.setFocus()

    def _choose_language(self, language: Language) -> None:
        if language is current_language():
            return
        self._services.settings.set_device_language(language)
        self.chosen_language = language
        self.done(self.LANGUAGE_CHANGED)

    def _apply(self) -> None:
        from servesync.ui.dialogs.application_dialog import ApplicationDialog  # only needed if someone applies

        ApplicationDialog(self._services, self).exec()

    def _sign_in(self) -> None:
        self.error.hide()
        try:
            with BusyCursor():
                self.session = self._services.auth.sign_in(self.username.text(), self.password.text())
        except AuthenticationError as error:
            self.error.setText(error.message)
            self.error.show()
            self.error.setAccessibleName(error.message)
            self.password.clear()
            self.password.setFocus()
            return
        self.accept()


class FirstRunDialog(QDialog):
    """First launch: explore the demo organization, or set up a real one."""

    DEMO = "demo"

    def __init__(self, services: Services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self.choice: str | None = None
        self.session: Session | None = None
        self.setWindowTitle(tr("Welcome to ServeSync"))
        self.setMinimumSize(900, 560)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        side = QWidget()
        column = QVBoxLayout(side)
        column.setContentsMargins(40, 40, 40, 32)
        column.setSpacing(14)
        column.addWidget(_wordmark())
        column.addSpacing(16)
        column.addWidget(headline(tr("Welcome to"), "ServeSync."))
        column.addWidget(
            make_label(tr("Choose how you'd like to begin. You can't do this step again later."), "subtitle", wrap=True)
        )

        demo = Panel(tr("Explore with sample data"))
        demo.body.addWidget(
            make_label(
                tr(
                    "Load Riverbend Community Alliance, a fictional nonprofit with 40 "
                    "volunteers, eight programs, and four months of history."
                ),
                wrap=True,
            )
        )
        demo.body.addWidget(make_button(tr("Load the demo organization"), kind="primary", on_click=self._load_demo))
        column.addWidget(demo)

        setup = Panel(tr("Set up your organization"))
        form = QFormLayout()
        self.org = QLineEdit()
        self.org.setMaxLength(80)
        self.username = QLineEdit()
        self.username.setMaxLength(30)
        self.password = _password_field(tr("At least 10 characters with a letter and a number"))
        self.confirm = _password_field()
        self._fields: dict[str, QLineEdit] = {
            "organization_name": self.org,
            "username": self.username,
            "password": self.password,
            "confirm_password": self.confirm,
        }
        for text, field in (
            (tr("Organization name"), self.org),
            (tr("Administrator username"), self.username),
            (tr("Password"), self.password),
            (tr("Confirm password"), self.confirm),
        ):
            label = QLabel(text)
            label.setBuddy(field)
            field.setAccessibleName(text)
            form.addRow(label, field)
        setup.body.addLayout(form)
        self.error = make_label("", "banner-error", wrap=True)
        self.error.hide()
        setup.body.addWidget(self.error)
        setup.body.addWidget(make_button(tr("Create administrator account"), on_click=self._create_admin))
        column.addWidget(setup)
        column.addStretch(1)
        row.addWidget(_scrolling(side), 1)
        row.addWidget(_brand_panel(tr("Let's get your organization started."), ""), 1)

    def _load_demo(self) -> None:
        try:
            with BusyCursor():
                self._services.setup.load_demo_data()
        except ServeSyncError as error:
            self.error.setText(error.message)
            self.error.show()
            return
        self.choice = self.DEMO
        self.accept()

    def _create_admin(self) -> None:
        self.error.hide()
        try:
            with BusyCursor():
                self.session = self._services.setup.create_first_admin(
                    organization_name=self.org.text(),
                    username=self.username.text(),
                    password=self.password.text(),
                    confirm=self.confirm.text(),
                )
        except ValidationError as error:
            self.error.setText("\n".join(error.errors.values()))
            self.error.show()
            first = next((self._fields[name] for name in error.errors if name in self._fields), None)
            if first is not None:
                first.setFocus(Qt.FocusReason.OtherFocusReason)
            return
        except ServeSyncError as error:
            self.error.setText(error.message)
            self.error.show()
            return
        self.choice = "admin"
        self.accept()


class ChangePasswordDialog(FormDialog):
    def __init__(self, services: Services, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(
            tr("Change password"),
            tr("Choose a password of at least 10 characters that includes a letter and a number."),
            parent,
            save_text=tr("Change password"),
        )
        self._services = services
        self._session = session
        self.current = _password_field()
        self.new = _password_field()
        self.confirm = _password_field()
        self.add_field("current_password", tr("Current password"), self.current)
        self.add_field("new_password", tr("New password"), self.new)
        self.add_field("confirm_password", tr("Confirm new password"), self.confirm)
        self.resize(520, 420)

    def submit(self) -> bool:
        with BusyCursor():
            self._services.auth.change_password(
                self._session, self.current.text(), self.new.text(), self.confirm.text()
            )
        return True
