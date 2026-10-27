"""Sign-in, first-launch setup, and password change dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from servesync.core.errors import AuthenticationError, ServeSyncError, ValidationError
from servesync.data.seed import DEMO_ORGANIZATION_NAME, DEMO_PASSWORD
from servesync.services import Services, Session
from servesync.ui import assets
from servesync.ui.widgets.common import BusyCursor, Panel, make_button, make_label
from servesync.ui.widgets.forms import FormDialog


def _password_field(placeholder: str = "") -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    field.setPlaceholderText(placeholder)
    field.setMaxLength(128)
    return field


def _brand_panel(organization: str, mission: str) -> QFrame:
    """The left half of the welcome screens: logo, name, and the organization's mission."""
    panel = QFrame()
    panel.setObjectName("TopBar")
    panel.setMinimumWidth(320)
    column = QVBoxLayout(panel)
    column.setContentsMargins(32, 36, 32, 32)
    column.setSpacing(10)
    logo = QLabel()
    logo.setPixmap(assets.logo_pixmap(56))
    logo.setAccessibleName("ServeSync logo")
    column.addWidget(logo)
    brand = QLabel("ServeSync")
    brand.setObjectName("Brand")
    column.addWidget(brand)
    org = QLabel(organization)
    org.setObjectName("OrgName")
    org.setWordWrap(True)
    column.addWidget(org)
    column.addSpacing(18)
    if mission:
        statement = make_label(mission, "mission", wrap=True)
        statement.setAccessibleName(f"Our mission: {mission}")
        column.addWidget(statement)
    column.addStretch(1)
    column.addWidget(make_label("Volunteer management for nonprofits", "figure-label", wrap=True))
    return panel


class LoginDialog(QDialog):
    """Sign in. Shows demo accounts only when the demo organization is loaded."""

    def __init__(self, services: Services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._services = services
        self.session: Session | None = None
        organization = services.settings.organization_name()
        self.setWindowTitle(f"Sign in - {organization}")
        self.setMinimumSize(820, 500)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(_brand_panel(organization, services.settings.mission_statement()))

        form_side = QWidget()
        column = QVBoxLayout(form_side)
        column.setContentsMargins(48, 48, 48, 36)
        column.setSpacing(12)
        column.addWidget(make_label("Sign in", "title"))
        column.addWidget(make_label("Use the username and password your coordinator gave you.", "subtitle", wrap=True))
        self.error = make_label("", "banner-error", wrap=True)
        self.error.hide()
        column.addWidget(self.error)

        form = QFormLayout()
        form.setVerticalSpacing(12)
        self.username = QLineEdit()
        self.username.setPlaceholderText("for example, jordan.rivera")
        self.username.setMaxLength(30)
        self.password = _password_field()
        for label_text, field in (("&Username", self.username), ("&Password", self.password)):
            label = QLabel(label_text)
            label.setBuddy(field)
            field.setAccessibleName(label_text.replace("&", ""))
            form.addRow(label, field)
        column.addLayout(form)

        self.sign_in_button = make_button("Sign in", kind="primary", on_click=self._sign_in)
        self.sign_in_button.setDefault(True)
        column.addWidget(self.sign_in_button)

        if organization == DEMO_ORGANIZATION_NAME:
            hint = Panel()
            hint.body.addWidget(make_label("Demo accounts", "section"))
            hint.body.addWidget(
                make_label(
                    "Leaders: admin, coordinator\nVolunteers: jordan.rivera, priya.patel\n"
                    f"Password for all: {DEMO_PASSWORD}",
                    "muted",
                    wrap=True,
                    selectable=True,
                )
            )
            column.addWidget(hint)
        column.addStretch(1)
        row.addWidget(form_side, 1)
        self.username.setFocus()

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
        self.setWindowTitle("Welcome to ServeSync")
        self.setMinimumSize(900, 560)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(_brand_panel("Let's get your organization started.", ""))

        side = QWidget()
        column = QVBoxLayout(side)
        column.setContentsMargins(40, 40, 40, 32)
        column.setSpacing(14)
        column.addWidget(make_label("Welcome to ServeSync", "title"))
        column.addWidget(
            make_label("Choose how you'd like to begin. You can't do this step again later.", "subtitle", wrap=True)
        )

        demo = Panel("Explore with sample data")
        demo.body.addWidget(
            make_label(
                "Load Riverbend Community Alliance, a fictional nonprofit with 40 volunteers, "
                "eight programs, and four months of history.",
                wrap=True,
            )
        )
        demo.body.addWidget(make_button("Load the demo organization", kind="primary", on_click=self._load_demo))
        column.addWidget(demo)

        setup = Panel("Set up your organization")
        form = QFormLayout()
        self.org = QLineEdit()
        self.org.setMaxLength(80)
        self.username = QLineEdit()
        self.username.setMaxLength(30)
        self.password = _password_field("At least 10 characters with a letter and a number")
        self.confirm = _password_field()
        self._fields: dict[str, QLineEdit] = {
            "organization_name": self.org,
            "username": self.username,
            "password": self.password,
            "confirm_password": self.confirm,
        }
        for text, field in (
            ("Organization name", self.org),
            ("Administrator username", self.username),
            ("Password", self.password),
            ("Confirm password", self.confirm),
        ):
            label = QLabel(text)
            label.setBuddy(field)
            field.setAccessibleName(text)
            form.addRow(label, field)
        setup.body.addLayout(form)
        self.error = make_label("", "banner-error", wrap=True)
        self.error.hide()
        setup.body.addWidget(self.error)
        setup.body.addWidget(make_button("Create administrator account", on_click=self._create_admin))
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
            "Change password",
            "Choose a password of at least 10 characters that includes a letter and a number.",
            parent,
            save_text="Change password",
        )
        self._services = services
        self._session = session
        self.current = _password_field()
        self.new = _password_field()
        self.confirm = _password_field()
        self.add_field("current_password", "Current password", self.current)
        self.add_field("new_password", "New password", self.new)
        self.add_field("confirm_password", "Confirm new password", self.confirm)
        self.resize(520, 420)

    def submit(self) -> bool:
        with BusyCursor():
            self._services.auth.change_password(
                self._session, self.current.text(), self.new.text(), self.confirm.text()
            )
        return True
