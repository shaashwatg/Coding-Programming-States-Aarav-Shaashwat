"""
Turn a finished ``Report`` into files: CSV for spreadsheets, HTML for the PDF.

Both honor the person's column choices, so what they see is what they export.

CSV safety: a cell that begins with ``=``, ``+``, ``-``, ``@``, tab or carriage
return could run as a formula when opened in Excel ("CSV injection"). Such
text cells get a leading apostrophe, the OWASP-recommended defense. Numbers
are written raw so spreadsheets can still calculate with them.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import date, datetime
from html import escape

from servesync import __app_name__
from servesync.services.reports.model import Report, ReportColumn, ReportKind, ValueKind, format_value

_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


def chosen_columns(report: Report, keys: Sequence[str] | None) -> list[ReportColumn]:
    """Columns to export, in report order (``None`` = the report's defaults)."""
    if keys is None:
        return [column for column in report.columns if column.shown_by_default]
    wanted = set(keys)
    return [column for column in report.columns if column.key in wanted]


def csv_cell(column: ReportColumn, value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if column.kind.is_numeric and isinstance(value, (int, float)):
        return f"{value:.2f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    text = str(value)
    return f"'{text}" if text.startswith(_FORMULA_STARTS) else text


def to_csv(report: Report, keys: Sequence[str] | None = None) -> str:
    """CSV text. Saved with a UTF-8 byte-order mark so Excel shows accents (José) correctly."""
    columns = chosen_columns(report, keys)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([column.label + (" (%)" if column.kind is ValueKind.PERCENT else "") for column in columns])
    for row in report.rows:
        writer.writerow([csv_cell(column, row.get(column.key)) for column in columns])
    return buffer.getvalue()


def suggested_filename(report: Report, extension: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in report.title.lower()).strip("-")
    return f"servesync-{safe}-{report.filters.start:%Y%m%d}-{report.filters.end:%Y%m%d}.{extension}"


def to_html(report: Report, keys: Sequence[str] | None = None, chart_images: Sequence[str] = ()) -> str:
    """
    A print-ready page for the PDF writer. ``chart_images`` are resource names
    of chart pictures already registered with the document.
    """
    columns = chosen_columns(report, keys)
    e = escape
    parts = [
        "<html><body style='font-family: sans-serif; color: #111;'>",
        f"<p style='color:#444; margin:0'>{e(report.organization_name)}</p>",
        f"<h1 style='margin:2px 0 4px 0'>{e(report.title)}</h1>",
        f"<p style='margin:0 0 2px 0'><b>{e(report.filters.describe())}</b></p>",
    ]
    parts += [f"<p style='margin:0'>{e(line)}</p>" for line in report.context]
    parts.append(
        f"<p style='color:#444; margin:4px 0 12px 0'>Prepared {e(format_value(ValueKind.DATE, report.generated_at))} "
        f"with {e(__app_name__)}</p>"
    )
    if report.figures:
        cells = "".join(
            f"<td style='padding:6px 14px 6px 0; vertical-align:top'><span style='font-size:16pt'><b>"
            f"{e(f.value)}</b></span><br>{e(f.label)}"
            f"{'<br><span style=color:#555>' + e(f.note) + '</span>' if f.note else ''}</td>"
            for f in report.figures
        )
        parts.append(f"<table><tr>{cells}</tr></table>")
    if report.insights:
        parts.append("<h3>What stands out</h3><ul>")
        parts += [f"<li>{e(insight)}</li>" for insight in report.insights]
        parts.append("</ul>")
    for name, chart in zip(chart_images, report.charts, strict=False):
        parts.append(f"<h3>{e(chart.title)}</h3><p><img src='{e(name)}' width='620'></p>")

    parts.append("<h3>Details</h3>")
    if report.is_empty:
        parts.append("<p>No records match these filters.</p>")
    else:
        header = "".join(
            f"<th align='{'right' if c.kind.is_numeric else 'left'}' style='border-bottom:1px solid #333; "
            f"padding:4px 6px'>{e(c.label)}</th>"
            for c in columns
        )
        body = []
        for index, row in enumerate(report.rows):
            shade = " style='background:#F2F2F2'" if index % 2 else ""
            cells = "".join(
                f"<td align='{'right' if c.kind.is_numeric else 'left'}' style='padding:3px 6px'>"
                f"{e(format_value(c.kind, row.get(c.key)))}</td>"
                for c in columns
            )
            body.append(f"<tr{shade}>{cells}</tr>")
        parts.append(f"<table cellspacing='0' width='100%'><tr>{header}</tr>{''.join(body)}</table>")

    if report.kind is ReportKind.SERVICE_RECORD:
        parts.append(
            "<p style='margin-top:28px'>Hours listed were recorded by the organization's coordinators when each "
            "shift was checked in.</p>"
            "<p style='margin-top:30px'>Coordinator signature: ______________________________"
            "&nbsp;&nbsp;&nbsp; Date: ______________</p>"
        )
    parts.append("</body></html>")
    return "".join(parts)
