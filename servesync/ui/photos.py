"""
Photo preparation: turns any picture a coordinator chooses into a JPEG under
300 kB, so screens stay fast. Large photos are resized to at most 1200 x 800
pixels, then saved at decreasing quality (and, if needed, smaller sizes)
until they fit.
"""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage

from servesync.core.errors import ValidationError
from servesync.core.i18n import tr
from servesync.data.photo_store import MAX_PHOTO_BYTES

MAX_WIDTH, MAX_HEIGHT = 1200, 800
QUALITY_STEPS = (85, 78, 70, 62, 55)


def _encode(image: QImage, quality: int) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, b"JPEG", quality)
    buffer.close()
    return bytes(data.data())


def prepare_photo(path: str) -> bytes:
    """Load a picture file and return web-optimized JPEG bytes (at most 300 kB)."""
    image = QImage(path)
    if image.isNull():
        raise ValidationError.single("photo", tr("That file isn't a picture ServeSync can open. Try a JPEG or PNG."))
    if image.width() < 200 or image.height() < 120:
        raise ValidationError.single(
            "photo", tr("That picture is too small to look good. Use one at least 200 pixels wide.")
        )
    image = image.convertToFormat(QImage.Format.Format_RGB32)
    if image.width() > MAX_WIDTH or image.height() > MAX_HEIGHT:
        image = image.scaled(
            MAX_WIDTH, MAX_HEIGHT, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
    while True:
        for quality in QUALITY_STEPS:
            data = _encode(image, quality)
            if len(data) <= MAX_PHOTO_BYTES:
                return data
        if image.width() < 300:
            raise ValidationError.single(
                "photo", tr("That picture couldn't be made small enough. Try a different one.")
            )
        image = image.scaledToWidth(int(image.width() * 0.8), Qt.TransformationMode.SmoothTransformation)
