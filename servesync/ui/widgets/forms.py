"""
Form building blocks: a dialog base with inline field errors, plus custom
inputs for weekly availability and skills.

Validation feedback follows three accessibility rules:
1. Every problem appears *next to its field*, in words (not only a red border).
2. All problems are shown at once, and focus jumps to the first one.
3. Each message is also set as the field's accessible description, so screen
   readers announce it.
"""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from servesync.core.errors import ServeSyncError, ValidationError
from servesync.models import AccessNeed, AvailabilitySlot, DayPart, Weekday
from servesync.ui.widgets.common import make_label, set_prop


class FormDialog(QDialog):
    """
    Base dialog: title, short instructions, a form whose rows each carry an
    error label, and Save / Cancel buttons. Subclasses call :meth:`add_field`
    and override :meth:`submit`.
    """

    def __init__(
        self, title: str, instructions: str, parent: QWidget | None = None, *, save_text: str = "Save"
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._fields: dict[str, tuple[QWidget, QLabel]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(12)
        heading = make_label(title, "title")
        outer.addWidget(heading)
        outer.addWidget(make_label(instructions, "subtitle", wrap=True))
        self.banner = make_label("", "banner-error", wrap=True)
        self.banner.hide()
        outer.addWidget(self.banner)

        body = QWidget()
        self.form = QFormLayout(body)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        self.form.setHorizontalSpacing(16)
        self.form.setVerticalSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.buttons = QDialogButtonBox()
        self.save_button = QPushButton(save_text)
        self.save_button.setProperty("kind", "primary")
        self.save_button.setDefault(True)
        self.buttons.addButton(self.save_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._on_save)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

    # -------------------------------------------------------------- building

    def add_field(self, name: str, label: str, widget: QWidget, hint: str = "") -> QWidget:
        """Add a labeled row with room for a hint and an error message under the input."""
        container = QWidget()
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 4)
        column.setSpacing(3)
        column.addWidget(widget)
        if hint:
            column.addWidget(make_label(hint, "hint", wrap=True))
        error = make_label("", "error", wrap=True)
        error.hide()
        column.addWidget(error)
        label_widget = QLabel(label)
        label_widget.setBuddy(widget)  # clicking the label focuses the field; screen readers pair them
        widget.setAccessibleName(label.replace("&", ""))
        self.form.addRow(label_widget, container)
        self._fields[name] = (widget, error)
        return widget

    def add_section(self, title: str) -> None:
        self.form.addRow(make_label(title, "section"))

    # -------------------------------------------------------------- errors

    def clear_errors(self) -> None:
        self.banner.hide()
        for widget, error in self._fields.values():
            error.hide()
            error.setText("")
            set_prop(widget, "invalid", False)
            widget.setAccessibleDescription("")

    def show_errors(self, errors: ValidationError | dict[str, str]) -> None:
        """Show each message under its field; unmatched messages go in the top banner."""
        self.clear_errors()
        messages = errors.errors if isinstance(errors, ValidationError) else errors
        leftover: list[str] = []
        first: QWidget | None = None
        for name, message in messages.items():
            if name in self._fields:
                widget, error = self._fields[name]
                error.setText(message)
                error.show()
                set_prop(widget, "invalid", True)
                widget.setAccessibleDescription(f"Error: {message}")
                first = first or widget
            else:
                leftover.append(message)
        if leftover:
            self.banner.setText("\n".join(leftover))
            self.banner.show()
        count = len(messages)
        self.banner.setAccessibleName(f"{count} problem{'s' if count != 1 else ''} to fix")
        if first is not None:
            first.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_message(self, message: str) -> None:
        self.clear_errors()
        self.banner.setText(message)
        self.banner.show()

    # -------------------------------------------------------------- saving

    def _on_save(self) -> None:
        try:
            if self.submit():
                self.accept()
        except ValidationError as error:
            self.show_errors(error)
        except ServeSyncError as error:
            self.show_message(error.message)

    def submit(self) -> bool:
        """Validate and save. Return True to close the dialog. Raise ValidationError to show errors."""
        raise NotImplementedError


class AvailabilityGrid(QWidget):
    """Seven days by three times of day, as labeled checkboxes (fully keyboard-accessible)."""

    def __init__(self) -> None:
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        self._boxes: dict[AvailabilitySlot, QCheckBox] = {}
        for column, part in enumerate(DayPart, start=1):
            header = make_label(part.label, "muted")
            grid.addWidget(header, 0, column, Qt.AlignmentFlag.AlignHCenter)
        for row, day in enumerate(Weekday, start=1):
            grid.addWidget(QLabel(day.label), row, 0)
            for column, part in enumerate(DayPart, start=1):
                box = QCheckBox()
                box.setAccessibleName(f"Available {day.label} {part.label.lower()}")
                box.setToolTip(f"{day.label} {part.label.lower()}")
                grid.addWidget(box, row, column, Qt.AlignmentFlag.AlignHCenter)
                self._boxes[AvailabilitySlot(day, part)] = box

    def slots(self) -> frozenset[AvailabilitySlot]:
        return frozenset(slot for slot, box in self._boxes.items() if box.isChecked())

    def set_slots(self, slots: Iterable[AvailabilitySlot]) -> None:
        chosen = set(slots)
        for slot, box in self._boxes.items():
            box.setChecked(slot in chosen)


class SkillPicker(QWidget):
    """Tick known skills or type a new one. Duplicates are prevented case-insensitively."""

    def __init__(self, known: Iterable[str]) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.list = QListWidget()
        self.list.setAccessibleName("Skills")
        self.list.setMaximumHeight(170)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        self.new_skill = QLineEdit()
        self.new_skill.setPlaceholderText("Add a skill that isn't listed")
        self.new_skill.setAccessibleName("New skill name")
        self.new_skill.setMaxLength(40)
        add = QPushButton("Add skill")
        add.clicked.connect(self._add_typed)
        self.new_skill.returnPressed.connect(self._add_typed)
        row.addWidget(self.new_skill, 1)
        row.addWidget(add)
        layout.addLayout(row)
        for name in sorted(set(known), key=str.casefold):
            self._add_item(name, checked=False)

    def _find(self, name: str) -> QListWidgetItem | None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is not None and item.text().casefold() == name.casefold():
                return item
        return None

    def _add_item(self, name: str, *, checked: bool) -> None:
        item = self._find(name)
        if item is None:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self.list.addItem(item)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def _add_typed(self) -> None:
        name = " ".join(self.new_skill.text().split())
        if name:
            self._add_item(name, checked=True)
            self.new_skill.clear()

    def skills(self) -> frozenset[str]:
        chosen = set()
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                chosen.add(item.text())
        return frozenset(chosen)

    def set_skills(self, skills: Iterable[str]) -> None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)
        for name in skills:
            self._add_item(name, checked=True)


class AccessPicker(QWidget):
    """
    Check boxes for access needs (on a volunteer) or access features (on a
    program). Same vocabulary both ways, worded for whoever is filling it in.
    """

    def __init__(self, *, for_program: bool) -> None:
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        self.boxes: dict[AccessNeed, QCheckBox] = {}
        for index, need in enumerate(AccessNeed):
            box = QCheckBox(need.offer_label if for_program else need.label)
            box.setAccessibleName(("Offers: " if for_program else "Needs: ") + box.text())
            grid.addWidget(box, index // 2, index % 2)
            self.boxes[need] = box

    def set_values(self, values: Iterable[AccessNeed]) -> None:
        chosen = set(values)
        for need, box in self.boxes.items():
            box.setChecked(need in chosen)

    def values(self) -> frozenset[AccessNeed]:
        return frozenset(need for need, box in self.boxes.items() if box.isChecked())
