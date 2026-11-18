"""Sign-in, first-launch setup, and password change dialogs."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from servesync.core.errors import AuthenticationError, ServeSyncError, ValidationError
from servesync.core.i18n import Language, current_language, tr
from servesync.data.seed import DEMO_ORGANIZATION_NAME, DEMO_PASSWORD
from servesync.services import Services, Session
from servesync.ui import assets
from servesync.ui.theme import current_palette
from servesync.ui.widgets.common import BusyCursor, Panel, make_button, make_label
from servesync.ui.widgets.forms import FormDialog


def _password_field(placeholder: str = "") -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setPlaceholderText(placeholder)
    field.setMaxLength(128)
    return field


class BrandPanel(QFrame):
    """
    The left half of the welcome screens: logo, name, and the organization's
    mission on deep navy, with the logo's rings spreading from one corner.
    """

    def __init__(self, organization: str, mission: str) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(340)
        self.setMaximumWidth(420)
        column = QVBoxLayout(self)
        column.setContentsMargins(40, 40, 40, 36)
        column.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(assets.logo_pixmap(current_palette().brand, 40))
        logo.setAccessibleName(tr("ServeSync logo"))
        top.addWidget(logo)
        brand = QLabel("ServeSync")
        brand.setObjectName("Brand")
        top.addWidget(brand, 1)
        column.addLayout(top)
        column.addStretch(2)
        org = make_label(organization, "sidebar-heading", wrap=True)
        org.setObjectName("OrgName")
        column.addWidget(org)
        column.addSpacing(10)
        if mission:
            statement = make_label(mission, "sidebar-lead", wrap=True)
            statement.setAccessibleName(tr("Our mission: {mission}", mission=mission))
            column.addWidget(statement)
        column.addStretch(3)
        column.addWidget(make_label(tr("Volunteer management for nonprofits"), "sidebar-muted", wrap=True))

    def paintEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        super().paintEvent(event)  # type: ignore[arg-type]
        palette = current_palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() * 1.02, self.height() * 1.0)
        step = min(self.width(), self.height()) * 0.2
        for index in range(4):
            painter.setPen(QPen(QColor(palette.sidebar_active if index < 2 else palette.sidebar_hover), 1.5))
            radius = step * (index + 1.5)
            painter.drawEllipse(center, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.sidebar_accent))
        painter.drawEllipse(QPointF(center.x() - step * 2.5 * 0.7071, center.y() - step * 2.5 * 0.7071), 5, 5)
        painter.end()


def _brand_panel(organization: str, mission: str) -> QFrame:
    return BrandPanel(organization, mission)


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
        self.setMinimumSize(820, 500)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(_brand_panel(organization, services.settings.mission_statement()))

        form_side = QWidget()
        outer = QVBoxLayout(form_side)
        outer.setContentsMargins(40, 24, 40, 32)
        outer.addWidget(language_switch(self._choose_language))
        outer.addStretch(1)
        centered = QHBoxLayout()
        centered.addStretch(1)
        holder = QWidget()
        holder.setMaximumWidth(400)
        holder.setMinimumWidth(320)
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(12)
        centered.addWidget(holder, 4)
        centered.addStretch(1)
        outer.addLayout(centered)
        outer.addStretch(2)
        column.addWidget(make_label(tr("Sign in"), "display"))
        column.addWidget(
            make_label(tr("Use the username and password your coordinator gave you."), "subtitle", wrap=True)
        )
        column.addSpacing(8)
        self.error = make_label("", "banner-error", wrap=True)
        self.error.hide()
        column.addWidget(self.error)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setVerticalSpacing(4)
        self.username = QLineEdit()
        self.username.setPlaceholderText(tr("for example, jordan.rivera"))
        self.username.setMaxLength(30)
        self.password = _password_field()
        for label_text, field in ((tr("&Username"), self.username), (tr("&Password"), self.password)):
            label = QLabel(label_text)
            label.setBuddy(field)
            field.setAccessibleName(label_text.replace("&", ""))
            form.addRow(label, field)
        column.addLayout(form)
        column.addSpacing(4)

        self.sign_in_button = make_button(tr("Sign in"), kind="primary", on_click=self._sign_in)
        self.sign_in_button.setDefault(True)
        column.addWidget(self.sign_in_button)
        new_here = QHBoxLayout()
        new_here.setSpacing(6)
        new_here.addStretch(1)
        new_here.addWidget(make_label(tr("New here?"), "muted"))
        self.apply_button = make_button(tr("Become a volunteer"), kind="link", on_click=self._apply)
        new_here.addWidget(self.apply_button)
        new_here.addStretch(1)
        column.addLayout(new_here)

        if organization == DEMO_ORGANIZATION_NAME:
            column.addSpacing(12)
            hint = Panel(card=False)
            hint.setProperty("inset", True)
            hint.body.setContentsMargins(16, 14, 16, 14)
            hint.body.setSpacing(4)
            hint.body.addWidget(make_label(tr("Demo accounts"), "strong"))
            hint.body.addWidget(
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
            column.addWidget(hint)
        row.addWidget(form_side, 1)
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
        row.addWidget(_brand_panel(tr("Let's get your organization started."), ""))

        side = QWidget()
        column = QVBoxLayout(side)
        column.setContentsMargins(40, 40, 40, 32)
        column.setSpacing(14)
        column.addWidget(make_label(tr("Welcome to ServeSync"), "title"))
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
        row.addWidget(side, 1)

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
