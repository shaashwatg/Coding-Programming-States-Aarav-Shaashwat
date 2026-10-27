"""
Reports — customizable output for meaningful data analysis.

    [Report: Volunteer hours v] [Period: Last 30 days v] [From][To] [Program: All v]
    "Who served, how much, and who might need a check-in?"
    | 1,154 h | $41,706 | 31 of 34 | 35.8 h |          <- headline figures
    What stands out: plain-English insights           <- analysis, not just numbers
    [ bar chart ]  [ trend line ]                       <- keyboard-navigable charts
    [ sortable table; Columns menu chooses details ]   <- exactly what gets exported
    [Export CSV] [Save PDF]

Leaders see every report. Volunteers see this page as **My hours**: their
own service record, ready to save as a PDF for school or scholarships.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from servesync.core.errors import ValidationError
from servesync.models import OpportunityCategory
from servesync.services import Permission
from servesync.services.reports import DatePreset, Report, ReportFilters, ReportKind, format_value
from servesync.services.reports.export import suggested_filename
from servesync.ui import assets
from servesync.ui.context import AppContext
from servesync.ui.pages.base import Page
from servesync.ui.report_files import save_csv, save_pdf
from servesync.ui.theme import current_palette
from servesync.ui.widgets.charts import ChartView
from servesync.ui.widgets.common import (
    BusyCursor,
    EnumComboBox,
    PageHeader,
    Panel,
    clear_layout,
    from_qdate,
    guarded,
    make_button,
    make_label,
    to_qdate,
)
from servesync.ui.widgets.table import Column, RecordTable

Row = dict[str, object]


class ReportsPage(Page):
    key = "reports"
    title = "Reports"
    icon_name = "chart-column"

    def __init__(self, ctx: AppContext) -> None:
        self.leader = ctx.session.can(Permission.VIEW_REPORTS)
        if not self.leader:
            self.key, self.title, self.icon_name = "hours", "My hours", "clock"
        super().__init__(ctx, scrollable=True)
        self.report: Report | None = None
        self.hidden: dict[ReportKind, set[str]] = {}
        self.charts: list[ChartView] = []

        self.export_csv = make_button(
            "Export CSV", tooltip="Save exactly what you see as a spreadsheet file", on_click=self._export_csv
        )
        self.export_pdf = make_button(
            "Save PDF", kind="primary", tooltip="Save a printable copy", on_click=self._export_pdf
        )
        self.columns_button = QToolButton()
        self.columns_button.setText("Columns")
        self.columns_button.setAccessibleName("Choose columns")
        self.columns_button.setToolTip("Show or hide columns in the table and exports")
        self.columns_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.columns_button.setMenu(QMenu(self.columns_button))
        actions: list[QWidget] = (
            [self.columns_button, self.export_csv, self.export_pdf] if self.leader else [self.export_pdf]
        )
        self.header = PageHeader(
            self.title,
            "Pick a question and a period. Everything here can be sorted and exported exactly as shown."
            if self.leader
            else "Your verified service, ready to save as a PDF for school, scholarships, or employers.",
            actions,
        )
        self.layout_.addWidget(self.header)

        # ---------------------------------------------------------- filters
        controls = QGridLayout()
        controls.setHorizontalSpacing(12)
        controls.setVerticalSpacing(4)
        self.kind_box = QComboBox()
        kinds = [k for k in ReportKind if self.leader or k is ReportKind.SERVICE_RECORD]
        for kind in kinds:
            self.kind_box.addItem(kind.label, kind.value)
        self.period_box = QComboBox()
        for preset in DatePreset:
            self.period_box.addItem(preset.value, preset.name)
        self.start = QDateEdit()
        self.end = QDateEdit()
        for edit in (self.start, self.end):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("MM/dd/yyyy")
        self.program_box = QComboBox()
        self.category_box: EnumComboBox[OpportunityCategory] = EnumComboBox(
            OpportunityCategory, all_label="All categories"
        )
        self.volunteer_box = QComboBox()
        self.include_inactive = QCheckBox("Include archived volunteers")
        fields: list[tuple[str, QWidget]] = [("Report", self.kind_box)] if self.leader else []
        fields += [("Period", self.period_box), ("From", self.start), ("To", self.end)]
        if self.leader:
            fields += [
                ("Program", self.program_box),
                ("Category", self.category_box),
                ("Volunteer", self.volunteer_box),
            ]
        self.field_labels: dict[QWidget, QWidget] = {}
        per_row = 4  # wraps onto a second row so large text never squeezes a field
        for index, (label, widget) in enumerate(fields):
            caption = make_label(label, "hint")
            caption.setBuddy(widget)
            widget.setAccessibleName(label)
            row, column = divmod(index, per_row)
            controls.addWidget(caption, row * 2, column)
            controls.addWidget(widget, row * 2 + 1, column)
            self.field_labels[widget] = caption
        for column in range(per_row):
            controls.setColumnStretch(column, 1)
        self.layout_.addLayout(controls)
        options = QHBoxLayout()
        self.question = make_label("", "muted", wrap=True)
        options.addWidget(self.question, 1)
        options.addWidget(self.include_inactive)
        self.layout_.addLayout(options)
        self.errors = make_label("", "banner-error", wrap=True)
        self.errors.hide()
        self.layout_.addWidget(self.errors)

        # ---------------------------------------------------------- output
        self.figures_row = QHBoxLayout()
        self.figures_row.setSpacing(12)
        self.layout_.addLayout(self.figures_row)
        self.insights = Panel("What stands out")
        self.insight_list = QVBoxLayout()
        self.insight_list.setSpacing(6)
        self.insights.body.addLayout(self.insight_list)
        self.layout_.addWidget(self.insights)
        self.chart_row = QHBoxLayout()
        self.chart_row.setSpacing(12)
        self.layout_.addLayout(self.chart_row)
        self.table_holder = QVBoxLayout()
        self.layout_.addLayout(self.table_holder)
        self.table: RecordTable[Row] | None = None

        self._resolve_dates()
        self.kind_box.currentIndexChanged.connect(self._kind_changed)
        self.period_box.currentIndexChanged.connect(self._period_changed)
        for widget in (self.start, self.end):
            widget.dateChanged.connect(lambda _d: self._filters_changed())
        for box in (self.program_box, self.category_box, self.volunteer_box):
            box.currentIndexChanged.connect(lambda _i: self._filters_changed())
        self.include_inactive.toggled.connect(lambda _on: self._filters_changed())
        self._kind_changed(apply=False)

    # ------------------------------------------------------------ choices

    @property
    def kind(self) -> ReportKind:
        return ReportKind(self.kind_box.currentData())

    def _resolve_dates(self) -> None:
        preset = DatePreset[self.period_box.currentData()]
        if preset is DatePreset.CUSTOM:
            return
        start, end = preset.resolve(self.ctx.services.clock.now().date())
        for edit, day in ((self.start, start), (self.end, end)):
            edit.blockSignals(True)
            edit.setDate(to_qdate(day))
            edit.blockSignals(False)

    def _period_changed(self) -> None:
        custom = DatePreset[self.period_box.currentData()] is DatePreset.CUSTOM
        self._resolve_dates()
        for edit in (self.start, self.end):
            edit.setEnabled(custom)
        self._filters_changed()

    def _kind_changed(self, *_args: object, apply: bool = True) -> None:
        kind = self.kind
        self.question.setText(kind.question)
        is_record = kind is ReportKind.SERVICE_RECORD
        default = DatePreset.SCHOOL_YEAR if is_record else DatePreset.LAST_30_DAYS
        self.period_box.blockSignals(True)
        self.period_box.setCurrentIndex(self.period_box.findData(default.name))
        self.period_box.blockSignals(False)
        for edit in (self.start, self.end):
            edit.setEnabled(False)
        self._resolve_dates()
        if self.leader:
            self._set_visible(self.volunteer_box, is_record)
            self._set_visible(self.program_box, not is_record)
            self._set_visible(self.category_box, not is_record)
        self.include_inactive.setVisible(kind is ReportKind.VOLUNTEER_HOURS)
        self.columns_button.setVisible(self.leader)
        if apply:
            self.reload()

    def _set_visible(self, widget: QWidget, visible: bool) -> None:
        widget.setVisible(visible)
        self.field_labels[widget].setVisible(visible)

    def _filters_changed(self) -> None:
        if self.isVisible():
            self.reload()
        else:
            self._dirty = True

    def apply_options(self, **options: Any) -> None:
        """Other screens (and Ask ServeSync) can open a specific report."""
        kind = options.get("kind")
        if isinstance(kind, str) and self.kind_box.findData(kind) >= 0:
            self.kind_box.blockSignals(True)
            self.kind_box.setCurrentIndex(self.kind_box.findData(kind))
            self.kind_box.blockSignals(False)
            self._kind_changed(apply=False)
        self._populate_choices()
        for key, box in (("opportunity_id", self.program_box), ("volunteer_id", self.volunteer_box)):
            value = options.get(key)
            if isinstance(value, int) and box.findData(value) >= 0:
                box.blockSignals(True)
                box.setCurrentIndex(box.findData(value))
                box.blockSignals(False)

    def _populate_choices(self) -> None:
        if not self.leader:
            return
        services, session = self.ctx.services, self.ctx.session
        for box, items, all_label in (
            (
                self.program_box,
                [(o.title, o.opportunity_id) for o in services.opportunities.find_all(session)],
                "All programs",
            ),
            (self.volunteer_box, [(v.full_name, v.volunteer_id) for v in services.volunteers.search(session)], None),
        ):
            current = box.currentData()
            box.blockSignals(True)
            box.clear()
            if all_label:
                box.addItem(all_label, None)
            for text, record_id in items:
                box.addItem(text, record_id)
            index = box.findData(current)
            box.setCurrentIndex(max(index, 0))
            box.blockSignals(False)

    def _filters(self) -> ReportFilters:
        volunteer = self.volunteer_box.currentData() if self.leader and self.kind is ReportKind.SERVICE_RECORD else None
        program = self.program_box.currentData() if self.leader and self.kind is not ReportKind.SERVICE_RECORD else None
        category = self.category_box.value() if self.leader and self.kind is not ReportKind.SERVICE_RECORD else None
        return ReportFilters(
            from_qdate(self.start.date()),
            from_qdate(self.end.date()),
            opportunity_id=program,
            category=category,
            include_inactive=self.include_inactive.isChecked(),
            volunteer_id=volunteer if volunteer is not None else self.ctx.session.volunteer_id,
        )

    # ------------------------------------------------------------ refresh

    def refresh(self) -> None:
        if self.table is None or (self.report is not None and self.report.kind is not self.kind):
            self._populate_choices()
        self.errors.hide()
        try:
            report = self.ctx.services.reports.build(self.ctx.session, self.kind, self._filters())
        except ValidationError as error:
            self.errors.setText("\n".join(error.errors.values()))
            self.errors.show()
            return
        animate = self.report is None or self.report.kind is not report.kind
        self.report = report
        self._show_figures(report)
        self._show_insights(report)
        self._show_charts(report, animate)
        self._show_table(report)
        self.export_csv.setEnabled(not report.is_empty)
        self.export_pdf.setEnabled(True)
        self.ctx.announce(
            f"{report.title}: {len(report.rows)} rows. " + (report.insights[0] if report.insights else "")
        )

    def _show_figures(self, report: Report) -> None:
        clear_layout(self.figures_row)
        for figure in report.figures:
            tile = Panel()
            tile.setProperty("tile", True)
            tile.body.setSpacing(2)
            value = make_label(figure.value, "figure")
            label = make_label(figure.label, "figure-label", wrap=True)
            tile.body.addWidget(value)
            tile.body.addWidget(label)
            if figure.note:
                tile.body.addWidget(make_label(figure.note, "hint", wrap=True))
            tile.setAccessibleName(f"{figure.label}: {figure.value}" + (f", {figure.note}" if figure.note else ""))
            self.figures_row.addWidget(tile, 1)

    def _show_insights(self, report: Report) -> None:
        clear_layout(self.insight_list)
        self.insights.setVisible(bool(report.insights))
        color = current_palette().info
        for insight in report.insights:
            row = QHBoxLayout()
            bulb = make_label()
            bulb.setPixmap(assets.pixmap("lightbulb", color, 18))
            bulb.setAlignment(Qt.AlignmentFlag.AlignTop)
            row.addWidget(bulb)
            row.addWidget(make_label(insight, "insight", wrap=True), 1)
            holder = QWidget()
            holder.setLayout(row)
            self.insight_list.addWidget(holder)

    def _show_charts(self, report: Report, animate: bool) -> None:
        clear_layout(self.chart_row)
        self.charts = []
        for series in report.charts:
            panel = Panel(series.title)
            chart = ChartView()
            chart.set_series(series, animated=animate)
            chart.item_focused.connect(self.ctx.announce)
            panel.body.addWidget(chart)
            panel.body.addWidget(make_label("Tip: select the chart and use the arrow keys to hear each value.", "hint"))
            self.chart_row.addWidget(panel, 1)
            self.charts.append(chart)

    def _show_table(self, report: Report) -> None:
        if self.table is None or self.table.property("kind") != report.kind.value:
            clear_layout(self.table_holder)
            columns = [
                Column[Row](
                    c.label,
                    lambda row, c=c: format_value(c.kind, row.get(c.key)),  # type: ignore[misc]
                    sort=lambda row, c=c: row.get(c.key),  # type: ignore[misc]
                    align_right=c.kind.is_numeric,
                    stretch=index == 0 and not c.kind.is_numeric,
                )
                for index, c in enumerate(report.columns)
            ]
            self.table = RecordTable(
                columns,
                empty_message="No records match these filters. Try a longer period or All programs.",
                accessible_name=f"{report.title} table",
            )
            self.table.setProperty("kind", report.kind.value)
            self.table.setMinimumHeight(320)
            self.table_holder.addWidget(self.table)
            self._build_column_menu(report)
        self.table.set_records(list(report.rows))
        self._apply_column_visibility(report)

    def _build_column_menu(self, report: Report) -> None:
        menu = self.columns_button.menu()
        menu.clear()
        hidden = self.hidden.setdefault(report.kind, {c.key for c in report.columns if not c.shown_by_default})
        for column in report.columns:
            action = menu.addAction(column.label)
            action.setCheckable(True)
            action.setChecked(column.key not in hidden)
            action.toggled.connect(lambda on, key=column.key: self._toggle_column(key, on))

    def _toggle_column(self, key: str, shown: bool) -> None:
        if self.report is None:
            return
        hidden = self.hidden.setdefault(self.report.kind, set())
        if shown:
            hidden.discard(key)
        else:
            hidden.add(key)
        self._apply_column_visibility(self.report)
        self.ctx.announce(f"{self.report.column(key).label} column {'shown' if shown else 'hidden'}")

    def _apply_column_visibility(self, report: Report) -> None:
        if self.table is None:
            return
        hidden = self.hidden.get(report.kind, {c.key for c in report.columns if not c.shown_by_default})
        for position, column in enumerate(report.columns):
            self.table.view.setColumnHidden(position, column.key in hidden)

    def visible_columns(self) -> list[str]:
        if self.report is None:
            return []
        hidden = self.hidden.get(self.report.kind, set())
        return [c.key for c in self.report.columns if c.key not in hidden]

    # ------------------------------------------------------------ export

    def _ask_path(self, extension: str, description: str) -> Path | None:
        assert self.report is not None
        start = Path.home() / "Documents" / suggested_filename(self.report, extension)
        chosen, _ = QFileDialog.getSaveFileName(
            self, f"Save {description}", str(start), f"{description} (*.{extension})"
        )
        if not chosen:
            return None
        path = Path(chosen)
        return path if path.suffix.lower() == f".{extension}" else path.with_suffix(f".{extension}")

    @guarded
    def _export_csv(self) -> None:
        if self.report is None:
            return
        path = self._ask_path("csv", "CSV spreadsheet")
        if path is not None:
            save_csv(self.report, path, self.visible_columns())
            self.ctx.events.status_message.emit(f"Saved {path.name}.")

    @guarded
    def _export_pdf(self) -> None:
        if self.report is None:
            return
        path = self._ask_path("pdf", "PDF document")
        if path is not None:
            with BusyCursor():
                images = [chart.render_image() for chart in self.charts]
                save_pdf(self.report, path, self.visible_columns() if self.leader else None, images)
            self.ctx.events.status_message.emit(f"Saved {path.name}.")
