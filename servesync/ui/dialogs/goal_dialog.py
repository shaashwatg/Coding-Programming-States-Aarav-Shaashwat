"""
A volunteer's personal hour goal: the home-page panel and the form that sets it.

Students often need a set number of service hours by a date. The panel turns
that into a plain next step ("about 2 hours a week"), in words as well as a bar.
"""

from __future__ import annotations

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDateEdit, QHBoxLayout, QProgressBar, QSpinBox, QWidget

from servesync.core.i18n import tr
from servesync.services.volunteer_service import MAX_HOUR_GOAL
from servesync.ui.context import AppContext
from servesync.ui.widgets.common import (
    Panel,
    format_date,
    format_hours,
    from_qdate,
    guarded,
    make_button,
    make_label,
    to_qdate,
)
from servesync.ui.widgets.forms import FormDialog

DEFAULT_GOAL_HOURS = 40
DEFAULT_GOAL_MONTHS = 6


class HourGoalDialog(FormDialog):
    def __init__(self, ctx: AppContext, parent: QWidget | None = None) -> None:
        super().__init__(
            tr("My hour goal"),
            tr("Set the service hours you want to reach, such as a school requirement. Hours count from August 1."),
            parent,
        )
        self._ctx = ctx
        self._volunteer_id = ctx.session.volunteer_id or 0
        volunteer = ctx.services.volunteers.get(ctx.session, self._volunteer_id)
        self.hours = QSpinBox()
        self.hours.setRange(1, MAX_HOUR_GOAL)
        self.hours.setValue(volunteer.hour_goal or DEFAULT_GOAL_HOURS)
        self.add_field("hour_goal", tr("Hours"), self.hours)
        self.due = QDateEdit()
        self.due.setCalendarPopup(True)
        self.due.setDisplayFormat("MM/dd/yyyy")
        due = volunteer.hour_goal_due
        self.due.setDate(to_qdate(due) if due else QDate.currentDate().addMonths(DEFAULT_GOAL_MONTHS))
        self.add_field("hour_goal_due", tr("By this date"), self.due)
        self.resize(520, 300)

    def submit(self) -> bool:
        self._ctx.services.volunteers.set_hour_goal(
            self._ctx.session, self._volunteer_id, self.hours.value(), from_qdate(self.due.date())
        )
        return True


class HourGoalPanel(Panel):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(tr("My hour goal"))
        self._ctx = ctx
        self.summary = make_label("", wrap=True)
        self.body.addWidget(self.summary)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setAccessibleName(tr("Progress toward my hour goal"))
        self.body.addWidget(self.bar)
        self.advice = make_label("", "muted", wrap=True)
        self.body.addWidget(self.advice)
        actions = QHBoxLayout()
        self.set_button = make_button(tr("Set a goal"), on_click=self._set_goal)
        self.clear_button = make_button(tr("Remove goal"), on_click=self._clear_goal)
        actions.addWidget(self.set_button)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        self.body.addLayout(actions)

    def refresh(self) -> None:
        progress = self._ctx.services.volunteers.hour_goal_progress(
            self._ctx.session, self._ctx.session.volunteer_id or 0
        )
        has_goal = progress is not None
        self.bar.setVisible(has_goal)
        self.advice.setVisible(has_goal)
        self.clear_button.setVisible(has_goal)
        self.set_button.setText(tr("Change goal") if has_goal else tr("Set a goal"))
        if progress is None:
            self.summary.setText(tr("Working toward a number of service hours? Set a goal and see your progress here."))
            return
        self.summary.setText(
            tr(
                "{served} of {goal} hours by {due}, counting from August 1",
                served=format_hours(progress.served),
                goal=progress.goal,
                due=format_date(progress.due),
            )
        )
        self.bar.setValue(round(progress.share * 100))
        if progress.reached:
            self.advice.setText(tr("Goal reached. Thank you!"))
        elif progress.days_left == 0:
            self.advice.setText(tr("The date has passed. Choose Change goal to set a new one."))
        elif progress.on_pace:
            self.advice.setText(
                tr("You're on pace. About {rate} a week gets you there.", rate=format_hours(progress.hours_per_week))
            )
        else:
            self.advice.setText(
                tr(
                    "You're a little behind. About {rate} a week gets you there.",
                    rate=format_hours(progress.hours_per_week),
                )
            )

    @guarded
    def _set_goal(self) -> None:
        if HourGoalDialog(self._ctx, self).exec():
            self._ctx.changed(tr("Your hour goal is saved."))

    @guarded
    def _clear_goal(self) -> None:
        self._ctx.services.volunteers.clear_hour_goal(self._ctx.session, self._ctx.session.volunteer_id or 0)
        self._ctx.changed(tr("Your hour goal is removed."))
