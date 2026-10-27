"""
Saving reports to disk: CSV (for spreadsheets) and PDF (for printing or email).

Writes are *atomic*: the file is written to a temporary name beside the
target and then renamed, so a full disk or a crash never leaves a
half-written report behind. Problems become plain-English errors.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF, QUrl
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from servesync.core.errors import DataStoreError
from servesync.services.reports import Report
from servesync.services.reports.export import to_csv, to_html


def _atomic_write(path: Path, data: bytes) -> None:
    folder = path.parent
    try:
        handle, temp_name = tempfile.mkstemp(prefix=".servesync-", dir=folder)
        with os.fdopen(handle, "wb") as temp:
            temp.write(data)
        os.replace(temp_name, path)
    except OSError as exc:
        raise DataStoreError(
            f"Couldn't save to {path.name}. Check that the folder exists and isn't read-only, then try again."
        ) from exc


def save_csv(report: Report, path: Path, columns: Sequence[str] | None) -> None:
    # UTF-8 with a byte-order mark so Excel shows names like "José" correctly.
    _atomic_write(path, to_csv(report, columns).encode("utf-8-sig"))


def save_pdf(report: Report, path: Path, columns: Sequence[str] | None, charts: Sequence[QImage]) -> None:
    """Letter-size PDF: title block, figures, insights, charts, then the table."""
    document = QTextDocument()
    names = []
    for index, image in enumerate(charts):
        name = f"chart-{index}.png"
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), image)
        names.append(name)
    document.setHtml(to_html(report, columns, names))

    with tempfile.TemporaryDirectory(dir=path.parent if path.parent.exists() else None) as folder:
        temp_path = Path(folder) / "report.pdf"
        writer = QPdfWriter(str(temp_path))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.Letter))
        writer.setPageMargins(QMarginsF(16, 16, 16, 16), QPageLayout.Unit.Millimeter)
        writer.setTitle(f"{report.title} - {report.organization_name}")
        writer.setCreator("ServeSync")
        writer.setResolution(144)
        page = writer.pageLayout().paintRectPixels(writer.resolution())
        document.setPageSize(QSizeF(page.width(), page.height()))
        document.print_(writer)
        del writer  # flush and close the file before reading it
        try:
            data = temp_path.read_bytes()
        except OSError as exc:
            raise DataStoreError("The PDF couldn't be created. Try saving to a different folder.") from exc
    _atomic_write(path, data)
