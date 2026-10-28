"""
Program photos — the organization's own pictures of its work.

Photos are stored as files beside the database (``photos/program-12.jpg``)
rather than inside it, which keeps the database small and fast. Every photo
must be a JPEG no larger than 300 kB: the interface shrinks pictures to meet
that limit before saving, so screens load instantly even on an old laptop.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from servesync.core.errors import DataStoreError, ValidationError
from servesync.core.i18n import tr

logger = logging.getLogger(__name__)

MAX_PHOTO_BYTES = 300 * 1024
_JPEG_SIGNATURE = b"\xff\xd8\xff"


class PhotoStore:
    """Saves and loads one optional photo per program. ``folder=None`` keeps photos in memory (tests)."""

    def __init__(self, folder: Path | None) -> None:
        self._folder = folder
        self._memory: dict[int, bytes] = {}

    def _path(self, opportunity_id: int) -> Path:
        if self._folder is None:
            raise RuntimeError("This photo store keeps photos in memory.")
        return self._folder / f"program-{int(opportunity_id)}.jpg"

    def save(self, opportunity_id: int, data: bytes) -> None:
        # Syntactic: really a JPEG. Semantic: small enough to load quickly.
        if not data.startswith(_JPEG_SIGNATURE):
            raise ValidationError.single("photo", tr("Photos must be saved as JPEG images."))
        if len(data) > MAX_PHOTO_BYTES:
            raise ValidationError.single(
                "photo",
                tr(
                    "Photos must be {value} kB or smaller (this one is {value2} kB).",
                    value=MAX_PHOTO_BYTES // 1024,
                    value2=len(data) // 1024,
                ),
            )
        if self._folder is None:
            self._memory[opportunity_id] = bytes(data)
            return
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            # Write to a temporary file, then swap it in: a crash mid-save can't leave half a photo.
            handle, temp_name = tempfile.mkstemp(dir=self._folder, suffix=".tmp")
            with os.fdopen(handle, "wb") as temp_file:
                temp_file.write(data)
            os.replace(temp_name, self._path(opportunity_id))
        except OSError as exc:
            logger.exception("Could not save photo for program #%s", opportunity_id)
            raise DataStoreError(tr("The photo could not be saved. Check that the disk has free space.")) from exc

    def load(self, opportunity_id: int) -> bytes | None:
        if self._folder is None:
            return self._memory.get(opportunity_id)
        path = self._path(opportunity_id)
        try:
            return path.read_bytes() if path.exists() else None
        except OSError:
            logger.exception("Could not read photo %s", path)
            return None

    def delete(self, opportunity_id: int) -> None:
        if self._folder is None:
            self._memory.pop(opportunity_id, None)
            return
        try:
            self._path(opportunity_id).unlink(missing_ok=True)
        except OSError as exc:
            raise DataStoreError(tr("The photo could not be removed.")) from exc
