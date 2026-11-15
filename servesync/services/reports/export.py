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
from collections.abc import Collection, Sequence
from datetime import date, datetime
from html import escape

from servesync import __app_name__
from servesync.core.i18n import tr
from servesync.services.reports.model import Report, ReportColumn, ReportKind, ReportSection, ValueKind, format_value

# Ink for printed reports. Paper is always white, so these don't follow the screen theme;
# they are the light theme's slate, secondary slate and hairlines (see ui/theme.py).
PRINT_TEXT, PRINT_MUTED = "#1E2433", "#454D61"
PRINT_RULE, PRINT_RULE_STRONG = "#E3E6EE", "#7C8496"

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
    writer.writerow([column.title + (" (%)" if column.kind is ValueKind.PERCENT else "") for column in columns])
    for row in report.rows:
        writer.writerow([csv_cell(column, row.get(column.key)) for column in columns])
    return buffer.getvalue()


def suggested_filename(report: Report, extension: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in report.title.lower()).strip("-")
    return f"servesync-{safe}-{report.filters.start:%Y%m%d}-{report.filters.end:%Y%m%d}.{extension}"


def to_html(
    report: Report,
    keys: Sequence[str] | None = None,
    chart_images: Sequence[str] = (),
    verification_code: str = "",
    sections: Collection[ReportSection] | None = None,
) -> str:
    """
    A print-ready page for the PDF writer. ``chart_images`` are resource names
    of chart pictures already registered with the document. ``sections`` leaves
    out the parts a leader switched off (None = everything).
    """
    shown = set(ReportSection) if sections is None else set(sections)
    columns = chosen_columns(report, keys)
    e = escape
    parts = [
        f"<html><body style='font-family: sans-serif; color: {PRINT_TEXT};'>",
        f"<p style='color:{PRINT_MUTED}; margin:0'>{e(report.organization_name)}</p>",
        f"<h1 style='margin:2px 0 4px 0'>{e(report.title)}</h1>",
        f"<p style='margin:0 0 2px 0'><b>{e(report.filters.describe())}</b></p>",
    ]
    parts += [f"<p style='margin:0'>{e(line)}</p>" for line in report.context]
    generated = format_value(ValueKind.DATE, report.generated_at)
    prepared = tr("Prepared {date} with {app}", date=generated, app=__app_name__)
    parts.append(f"<p style='color:{PRINT_MUTED}; margin:4px 0 12px 0'>{e(prepared)}</p>")
    if report.figures and ReportSection.FIGURES in shown:
        cells = "".join(
            f"<td style='padding:6px 14px 6px 0; vertical-align:top'><span style='font-size:16pt'><b>"
            f"{e(f.value)}</b></span><br>{e(f.label)}"
            f"{f'<br><span style=color:{PRINT_MUTED}>' + e(f.note) + '</span>' if f.note else ''}</td>"
            for f in report.figures
        )
        parts.append(f"<table><tr>{cells}</tr></table>")
    if report.insights and ReportSection.INSIGHTS in shown:
        parts.append(f"<h3>{e(tr('What stands out'))}</h3><ul>")
        parts += [f"<li>{e(insight)}</li>" for insight in report.insights]
        parts.append("</ul>")
    for name, chart in zip(chart_images if ReportSection.CHARTS in shown else (), report.charts, strict=False):
        parts.append(f"<h3>{e(chart.title)}</h3><p><img src='{e(name)}' width='620'></p>")

    if ReportSection.TABLE not in shown:
        pass
    elif report.is_empty:
        parts.append(f"<h3>{e(tr('Details'))}</h3>")
        parts.append(f"<p>{e(tr('No records match these filters.'))}</p>")
    else:
        parts.append(f"<h3>{e(tr('Details'))}</h3>")
        header = "".join(
            f"<th align='{'right' if c.kind.is_numeric else 'left'}' "
            f"style='border-bottom:1px solid {PRINT_RULE_STRONG}; "
            f"padding:4px 6px'>{e(c.title)}</th>"
            for c in columns
        )
        body = []
        for row in report.rows:  # no zebra stripes: a hairline under each row reads more calmly
            cells = "".join(
                f"<td align='{'right' if c.kind.is_numeric else 'left'}' "
                f"style='padding:4px 6px; border-bottom:1px solid {PRINT_RULE}'>"
                f"{e(format_value(c.kind, row.get(c.key)))}</td>"
                for c in columns
            )
            body.append(f"<tr>{cells}</tr>")
        parts.append(f"<table cellspacing='0' width='100%'><tr>{header}</tr>{''.join(body)}</table>")

    if report.kind is ReportKind.SERVICE_RECORD:
        recorded = tr("Hours listed were recorded by the organization's coordinators when each shift was checked in.")
        parts.append(
            f"<p style='margin-top:28px'>{e(recorded)}</p>"
            f"<p style='margin-top:30px'>{e(tr('Coordinator signature:'))} ______________________________"
            f"&nbsp;&nbsp;&nbsp; {e(tr('Date:'))} ______________</p>"
        )
        if verification_code:
            parts.append(
                f"<p style='margin-top:18px; color:{PRINT_MUTED}'>"
                f"{e(tr('Verification code: {code}', code=verification_code))}<br>"
                f"{e(tr('The organization can confirm this record with this code.'))}</p>"
            )
    parts.append("</body></html>")
    return "".join(parts)
