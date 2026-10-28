"""Pure business-rule tests: no database, no clock — just facts in, decisions out."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from servesync.core.errors import BusinessRuleError
from servesync.models import OpportunityCategory, OpportunityStatus, ShiftOverview, VolunteerStatus
from servesync.services.rules import (
    check_opportunity_transition,
    check_volunteer_transition,
    describe_names,
    signup_blockers,
)
from tests.conftest import NOW, SATURDAY_9AM
from tests.factories import make_shift, make_volunteer


def _overview(
    *,
    filled: int = 0,
    capacity: int = 2,
    status: OpportunityStatus = OpportunityStatus.OPEN,
    start: datetime = SATURDAY_9AM,
) -> ShiftOverview:
    return ShiftOverview(
        shift=make_shift(1, start, capacity=capacity),
        opportunity_title="Food Pantry",
        category=OpportunityCategory.FOOD_SECURITY,
        location="Hall",
        opportunity_status=status,
        filled=filled,
    )


def _blockers(**overrides: object) -> list[str]:
    facts: dict[str, object] = {
        "volunteer": make_volunteer(),
        "overview": _overview(),
        "min_age": 14,
        "now": NOW,
        "already_signed_up": False,
        "has_conflict": False,
    }
    facts.update(overrides)
    return signup_blockers(**facts)  # type: ignore[arg-type]


def test_eligible_volunteer_has_no_blockers() -> None:
    assert _blockers() == []


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"volunteer": make_volunteer(status=VolunteerStatus.APPLICANT)}, "Applicant"),
        ({"overview": _overview(status=OpportunityStatus.DRAFT)}, "not taking sign-ups"),
        ({"overview": _overview(start=NOW - timedelta(hours=1))}, "already started"),
        ({"overview": _overview(filled=2)}, "full"),
        ({"min_age": 40}, "aged 40+"),
        ({"has_conflict": True}, "another shift"),
        ({"already_signed_up": True}, "already signed up"),
    ],
)
def test_each_rule_blocks_with_a_clear_reason(overrides: dict[str, object], expected: str) -> None:
    reasons = _blockers(**overrides)
    assert len(reasons) == 1 and expected in reasons[0]


def test_already_signed_up_is_not_also_reported_as_full() -> None:
    reasons = _blockers(overview=_overview(filled=2), already_signed_up=True)
    assert reasons == ["Ana Lopez is already signed up for this shift."]


def test_all_reasons_are_reported_together() -> None:
    assert len(_blockers(overview=_overview(filled=2), has_conflict=True, min_age=60)) == 3


def test_age_is_measured_on_the_shift_date() -> None:
    turns_18_friday = make_volunteer(
        birth_date=date(2008, 11, 6),
        joined_on=date(2025, 1, 15),
        emergency_contact_name="Pat Lopez",
        emergency_contact_phone="404-555-0110",
    )
    assert _blockers(volunteer=turns_18_friday, min_age=18) == []  # 18 by Saturday's shift


def test_volunteer_transitions() -> None:
    check_volunteer_transition(VolunteerStatus.APPLICANT, VolunteerStatus.ACTIVE)
    check_volunteer_transition(VolunteerStatus.INACTIVE, VolunteerStatus.ACTIVE)
    with pytest.raises(BusinessRuleError, match="can't move"):
        check_volunteer_transition(VolunteerStatus.ACTIVE, VolunteerStatus.APPLICANT)
    with pytest.raises(BusinessRuleError, match="already"):
        check_volunteer_transition(VolunteerStatus.ACTIVE, VolunteerStatus.ACTIVE)


def test_opportunity_transitions() -> None:
    check_opportunity_transition(OpportunityStatus.DRAFT, OpportunityStatus.OPEN)
    check_opportunity_transition(OpportunityStatus.CLOSED, OpportunityStatus.OPEN)
    with pytest.raises(BusinessRuleError, match="back to Draft"):
        check_opportunity_transition(OpportunityStatus.OPEN, OpportunityStatus.DRAFT)


def test_describe_names() -> None:
    assert describe_names([]) == ""
    assert describe_names(["Ana"]) == "Ana"
    assert describe_names(["Ana", "Ben", "Cara"]) == "Ana, Ben and Cara"
    assert describe_names(["A", "B", "C", "D", "E"]) == "A, B, C and 2 more"
