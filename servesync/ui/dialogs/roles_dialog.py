"""
Roles within a shift: "Registration x2, Water station x6, First aid x1 (needs First Aid/CPR)".

A leader lists the jobs on a shift, how many people each needs, and, if it
matters, the one skill a person must have to take it. The shift's capacity
becomes the total. The service checks the rules (unique names, no role smaller
than the people already in it, no removing a role someone is signed up for);
this form only collects the rows and shows each problem beside its role.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from servesync.config import MAX_SHIFT_CAPACITY
from servesync.core.errors import ServeSyncError, ValidationError
from servesync.core.i18n import tr, tr_n
from servesync.models import RoleOverview, ShiftRole
from servesync.models.role import MAX_ROLES_PER_SHIFT, ROLE_NAME_MAX_LENGTH
from servesync.ui.context import AppContext
from servesync.ui.widgets.common import make_button, make_label, set_prop


class _RoleRow:
    """The widgets for one role, and the saved role they edit (None for a new one)."""

    def __init__(self, skills: list[str], role: ShiftRole | None, filled: int) -> None:
        self.role_id = role.role_id if role else None
        self.filled = filled
        self.name = QLineEdit(role.name if role else "")
        self.name.setMaxLength(ROLE_NAME_MAX_LENGTH)
        self.name.setPlaceholderText(tr("General"))
        self.name.setAccessibleName(tr("Role name"))
        self.capacity = QSpinBox()
        self.capacity.setRange(1, MAX_SHIFT_CAPACITY)
        self.capacity.setValue(role.capacity if role else 1)
        self.capacity.setAccessibleName(tr("People needed"))
        self.skill = QComboBox()
        self.skill.setEditable(True)
        self.skill.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.skill.addItem(tr("Anyone"), "")
        for name in skills:
            self.skill.addItem(name, name)
        self.skill.setAccessibleName(tr("Required skill"))
        if role and role.required_skill:
            index = self.skill.findData(role.required_skill)
            if index >= 0:
                self.skill.setCurrentIndex(index)
            else:
                self.skill.setEditText(role.required_skill)
        self.filled_label = make_label(tr_n("{count} signed up", "{count} signed up", filled) if filled else "", "hint")
        self.remove = make_button(tr("Remove"))
        self.remove.setEnabled(filled == 0)
        self.remove.setToolTip("" if filled == 0 else tr("Cancel or move the people in this role first."))

    def required_skill(self) -> str:
        text = self.skill.currentText().strip()
        return "" if text in ("", tr("Anyone")) else text

    def widgets(self) -> tuple[QWidget, ...]:
        return (self.name, self.capacity, self.skill, self.filled_label, self.remove)


class RolesDialog(QDialog):
    def __init__(
        self, ctx: AppContext, shift_id: int, roles: list[RoleOverview], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._shift_id = shift_id
        self._skills = ctx.services.volunteers.skill_names()
        self.setWindowTitle(tr("Roles on this shift"))
        self.resize(780, 640)

        column = QVBoxLayout(self)
        column.setContentsMargins(24, 24, 24, 16)
        column.setSpacing(16)
        column.addWidget(make_label(tr("Roles on this shift"), "title"))
        column.addWidget(
            make_label(
                tr(
                    "List each job and how many people it needs. Choose a skill only when the job "
                    "truly requires it: then only people with that skill can take it. The shift's "
                    "size becomes the total. Leave the name blank for a general role."
                ),
                "subtitle",
                wrap=True,
            )
        )
        self.banner = make_label("", "banner-error", wrap=True)
        self.banner.hide()
        column.addWidget(self.banner)

        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(8)
        for index, heading in enumerate((tr("Role"), tr("People needed"), tr("Required skill"))):
            self.grid.addWidget(make_label(heading, "hint"), 0, index)
        self.grid.setColumnStretch(0, 3)
        self.grid.setColumnStretch(2, 2)
        self.grid.setRowStretch(MAX_ROLES_PER_SHIFT + 1, 1)  # rows stay at their natural height
        scroll = QScrollArea()  # many roles, or large text, scroll instead of squeezing the rows
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(holder)
        column.addWidget(scroll, 1)

        self.total = make_label("", "muted")  # created before the rows, which update it
        self.rows: list[_RoleRow] = []
        for overview in roles:
            self._add_row(overview.role, overview.filled)
        self.add_button = make_button(tr("Add a role"), on_click=lambda: self._add_row(None, 0))
        column.addWidget(self.add_button)
        column.addWidget(self.total)

        buttons = QDialogButtonBox()
        save = QPushButton(tr("Save roles"))
        save.setProperty("kind", "primary")
        save.setDefault(True)
        buttons.addButton(save, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)
        self._update_total()

    # -------------------------------------------------------------- rows

    def _add_row(self, role: ShiftRole | None, filled: int) -> None:
        if len(self.rows) >= MAX_ROLES_PER_SHIFT:
            self._show(tr("A shift can have at most {count} roles.", count=MAX_ROLES_PER_SHIFT))
            return
        row = _RoleRow(self._skills, role, filled)
        row.remove.clicked.connect(lambda _checked=False, row=row: self._remove_row(row))
        row.capacity.valueChanged.connect(lambda _value: self._update_total())
        self.rows.append(row)
        self._relayout()
        row.name.setFocus()

    def _remove_row(self, row: _RoleRow) -> None:
        if len(self.rows) == 1:
            self._show(tr("A shift needs at least one role."))
            return
        self.rows.remove(row)
        for widget in row.widgets():
            widget.hide()
            widget.deleteLater()
        self._relayout()

    def _relayout(self) -> None:
        for index, row in enumerate(self.rows, start=1):
            for position, widget in enumerate(row.widgets()):
                self.grid.addWidget(widget, index, position)
        self._update_total()

    def _update_total(self) -> None:
        total = sum(row.capacity.value() for row in self.rows)
        self.total.setText(tr_n("The shift will need {count} person.", "The shift will need {count} people.", total))

    # ------------------------------------------------------------- saving

    def _show(self, message: str) -> None:
        self.banner.setText(message)
        self.banner.show()

    def _save(self) -> None:
        for row in self.rows:
            set_prop(row.name, "invalid", False)
            set_prop(row.capacity, "invalid", False)
        try:
            roles = []
            for position, row in enumerate(self.rows):
                try:
                    roles.append(
                        ShiftRole(
                            name=row.name.text(),
                            capacity=row.capacity.value(),
                            required_skill=row.required_skill(),
                            shift_id=self._shift_id,
                            position=position,
                            role_id=row.role_id,
                        )
                    )
                except ValidationError as error:  # name each problem's role, so it can be found
                    raise ValidationError({f"role_{position}_{k}": v for k, v in error.errors.items()}) from error
            self._ctx.services.scheduling.set_roles(self._ctx.session, self._shift_id, roles)
        except ValidationError as error:
            self._show_errors(error)
            return
        except ServeSyncError as error:
            self._show(error.message)
            return
        self.accept()

    def _show_errors(self, error: ValidationError) -> None:
        lines = []
        for key, message in error.errors.items():
            parts = key.split("_")
            if len(parts) >= 3 and parts[0] == "role" and parts[1].isdigit() and int(parts[1]) < len(self.rows):
                row = self.rows[int(parts[1])]
                set_prop(row.capacity if parts[2] == "capacity" else row.name, "invalid", True)
                label = row.name.text().strip() or tr("General")
                lines.append(tr("{role}: {message}", role=label, message=message))
            else:
                lines.append(message)
        self._show("\n".join(lines))
