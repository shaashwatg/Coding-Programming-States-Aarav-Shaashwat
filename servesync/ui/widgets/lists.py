"""
:class:`RowList`: a list whose rows are designed, not just lines of text.

Each row can lead with a person's initials or an icon, has a title and an
optional quieter second line, and can end with a status tag or a short note.
Used for the activity feed, applicants, expiring certifications, and any
other short list where a full table would be too heavy.

The row's plain text is still stored on the item (``item.text()``), so screen
readers and tests read exactly what is on screen.
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QResizeEvent, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from servesync.ui import assets
from servesync.ui.theme import current_palette, px, ui_font
from servesync.ui.widgets.elements import paint_avatar, paint_tag, tag_size

_BASE = int(Qt.ItemDataRole.UserRole) + 40
TITLE_ROLE, SUBTITLE_ROLE, AVATAR_ROLE, ICON_ROLE, TONE_ROLE, TRAILING_ROLE, TRAILING_TONE_ROLE, EMPTY_ROLE = (
    _BASE,
    _BASE + 1,
    _BASE + 2,
    _BASE + 3,
    _BASE + 4,
    _BASE + 5,
    _BASE + 6,
    _BASE + 7,
)
LEAD = 32  # avatar or icon badge size
AnyIndex = QModelIndex | QPersistentModelIndex


class RowDelegate(QStyledItemDelegate):
    def __init__(self, owner: RowList) -> None:
        super().__init__(owner)
        self._owner = owner

    def _layout(self, index: AnyIndex, width: float) -> tuple[float, float, float, float]:
        """(text left, text width, title height, subtitle height) for a row ``width`` wide."""
        owner = self._owner
        left = float(owner.edge)
        if index.data(AVATAR_ROLE) or index.data(ICON_ROLE):
            left += px(LEAD) + px(12)
        right = float(owner.edge)
        trailing = str(index.data(TRAILING_ROLE) or "")
        if trailing:
            if index.data(TRAILING_TONE_ROLE):
                right += tag_size(trailing).width() + px(12)
            else:
                right += QFontMetricsF(ui_font(0.93, 400, tabular=True)).horizontalAdvance(trailing) + px(12)
        text_width = max(width - left - right, px(80))
        title = str(index.data(TITLE_ROLE) or "")
        title_metrics = QFontMetricsF(ui_font(1.0, owner.title_weight))
        title_height = title_metrics.boundingRect(
            QRectF(0, 0, text_width, 10_000), int(Qt.TextFlag.TextWordWrap), title
        ).height()
        subtitle = str(index.data(SUBTITLE_ROLE) or "")
        subtitle_height = 0.0
        if subtitle:
            subtitle_height = (
                QFontMetricsF(ui_font(0.86))
                .boundingRect(QRectF(0, 0, text_width, 10_000), int(Qt.TextFlag.TextWordWrap), subtitle)
                .height()
            )
        return left, text_width, title_height, subtitle_height

    def sizeHint(self, option: QStyleOptionViewItem, index: AnyIndex) -> QSize:  # noqa: N802 - Qt API
        width = self._owner.viewport().width()
        _left, _text_width, title_height, subtitle_height = self._layout(index, width)
        height = title_height + subtitle_height + (px(2) if subtitle_height else 0) + px(22)
        return QSize(width, round(max(height, px(self._owner.min_row))))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: AnyIndex) -> None:
        palette = current_palette()
        owner = self._owner
        rect = QRectF(option.rect)
        state = option.state
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver) and owner.interactive
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if selected:
            painter.fillRect(rect, QColor(palette.selection))
        elif hovered:
            painter.fillRect(rect, QColor(palette.surface_hover))
        if index.row() < owner.count() - 1:
            painter.fillRect(
                QRectF(rect.left() + owner.edge, rect.bottom(), rect.width() - 2 * owner.edge, 1), QColor(palette.line)
            )

        if index.data(EMPTY_ROLE):
            painter.setFont(ui_font(1.0))
            painter.setPen(QColor(palette.text_muted))
            painter.drawText(
                rect.adjusted(owner.edge, 0, -owner.edge, 0),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap),
                str(index.data(TITLE_ROLE) or ""),
            )
            painter.restore()
            return

        left, text_width, title_height, subtitle_height = self._layout(index, rect.width())
        block = title_height + subtitle_height + (px(2) if subtitle_height else 0)
        top = rect.top() + (rect.height() - block) / 2

        # Leading: a person's initials, or an icon on a tinted square.
        lead = px(LEAD)
        lead_rect = QRectF(rect.left() + owner.edge, rect.top() + (rect.height() - lead) / 2, lead, lead)
        if block > lead + px(8):  # tall rows keep the picture beside the first line
            lead_rect.moveTop(top)
        avatar = index.data(AVATAR_ROLE)
        icon_name = index.data(ICON_ROLE)
        if avatar:
            paint_avatar(painter, lead_rect, str(avatar))
        elif icon_name:
            background, foreground = palette.tone(str(index.data(TONE_ROLE) or "info"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(background))
            painter.drawRoundedRect(lead_rect, lead * 0.28, lead * 0.28)
            glyph = round(lead * 0.5)
            image = assets.pixmap(str(icon_name), foreground, glyph)
            painter.drawPixmap(
                QRectF(lead_rect.center().x() - glyph / 2, lead_rect.center().y() - glyph / 2, glyph, glyph),
                image,
                QRectF(image.rect()),
            )

        wrap = QTextOption()
        wrap.setWrapMode(QTextOption.WrapMode.WordWrap)
        text_color = QColor(palette.on_selection if selected else palette.text)
        painter.setFont(ui_font(1.0, owner.title_weight))
        painter.setPen(text_color)
        painter.drawText(QRectF(rect.left() + left, top, text_width, title_height), str(index.data(TITLE_ROLE)), wrap)
        subtitle = str(index.data(SUBTITLE_ROLE) or "")
        if subtitle:
            painter.setFont(ui_font(0.86))
            painter.setPen(QColor(palette.on_selection if selected else palette.text_muted))
            painter.drawText(
                QRectF(rect.left() + left, top + title_height + px(2), text_width, subtitle_height), subtitle, wrap
            )

        trailing = str(index.data(TRAILING_ROLE) or "")
        if trailing:
            tone = index.data(TRAILING_TONE_ROLE)
            if tone:
                size = tag_size(trailing)
                box = QRectF(
                    rect.right() - owner.edge - size.width(),
                    rect.center().y() - size.height() / 2,
                    size.width(),
                    size.height(),
                )
                paint_tag(painter, box, trailing, str(tone))
            else:
                painter.setFont(ui_font(0.93, 400, tabular=True))
                painter.setPen(QColor(palette.on_selection if selected else palette.text_muted))
                painter.drawText(
                    rect.adjusted(0, 0, -owner.edge, 0),
                    int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                    trailing,
                )
        painter.restore()


class RowList(QListWidget):
    """
    A list of designed rows. ``interactive=False`` is for lists that only inform
    (the activity feed): rows do not highlight under the pointer or select.
    """

    def __init__(
        self,
        accessible_name: str,
        *,
        interactive: bool = True,
        edge: int = 18,
        min_row: int = 52,
        title_weight: int = 400,
    ) -> None:
        super().__init__()
        self.interactive = interactive
        self.edge = edge
        self.min_row = min_row
        self.title_weight = title_weight
        self.setAccessibleName(accessible_name)
        self.setProperty("flat", True)
        self.setItemDelegate(RowDelegate(self))
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if not interactive:
            self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    def add_row(
        self,
        title: str,
        subtitle: str = "",
        *,
        avatar: str | None = None,
        icon: str | None = None,
        tone: str = "info",
        trailing: str = "",
        trailing_tone: str | None = None,
        data: object = None,
        text: str | None = None,
        tooltip: str = "",
    ) -> QListWidgetItem:
        """
        Add a row. ``avatar`` is a person's name (their initials are drawn);
        ``icon`` an icon name on a ``tone`` tint. ``trailing`` is a short note at
        the right end, drawn as a status tag when ``trailing_tone`` is given.
        ``data`` is stored under ``Qt.ItemDataRole.UserRole``.
        """
        plain = text if text is not None else (f"{title}\n{subtitle}" if subtitle else title)
        item = QListWidgetItem(plain)
        item.setData(TITLE_ROLE, title)
        item.setData(SUBTITLE_ROLE, subtitle)
        item.setData(AVATAR_ROLE, avatar)
        item.setData(ICON_ROLE, icon)
        item.setData(TONE_ROLE, tone)
        item.setData(TRAILING_ROLE, trailing)
        item.setData(TRAILING_TONE_ROLE, trailing_tone)
        spoken = ", ".join(part for part in (title, subtitle, trailing) if part)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, spoken)
        if data is not None:
            item.setData(Qt.ItemDataRole.UserRole, data)
        if tooltip:
            item.setToolTip(tooltip)
        self.addItem(item)
        return item

    def set_empty(self, message: str) -> None:
        """Replace the rows with one quiet line saying why the list is empty."""
        self.clear()
        item = QListWidgetItem(message)
        item.setData(TITLE_ROLE, message)
        item.setData(EMPTY_ROLE, True)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        self.addItem(item)

    def content_height(self) -> int:
        self.doItemsLayout()
        rows = sum(self.sizeHintForRow(row) for row in range(self.count()))
        return rows + 2 * self.frameWidth() + 4

    def fit_contents(self, *, maximum: int = 420, minimum: int = 0) -> None:
        """Make the list as tall as its rows (up to ``maximum``), so short lists do not scroll."""
        self.setFixedHeight(max(min(self.content_height(), px(maximum)), minimum))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self.scheduleDelayedItemsLayout()  # row heights depend on the width (wrapped text)
