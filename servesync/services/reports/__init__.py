"""
Customizable reports: pick a question, a period, and a scope; get headline
figures, plain-English insights, charts, and a sortable table — then export
exactly what you see to CSV or PDF.

* ``model``     — filters, columns, and the finished ``Report`` (value objects)
* ``analytics`` — the math, as pure functions (unit tested)
* ``service``   — permission checks and data gathering
* ``export``    — CSV (injection-safe) and print-ready HTML
"""

from servesync.services.reports.model import (
    ChartSeries,
    DatePreset,
    Figure,
    Report,
    ReportColumn,
    ReportFilters,
    ReportKind,
    ValueKind,
    format_value,
)
from servesync.services.reports.service import ReportService

__all__ = [
    "ChartSeries",
    "DatePreset",
    "Figure",
    "Report",
    "ReportColumn",
    "ReportFilters",
    "ReportKind",
    "ReportService",
    "ValueKind",
    "format_value",
]
