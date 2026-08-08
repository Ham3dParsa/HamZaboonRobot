"""Grade policy definitions for the session engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GradePolicy:
    activity_type: str
    grade_source: str
    grade_mapping: MappingProxyType
    description: str


GRADE_POLICIES: dict[str, GradePolicy] = {
    "srs_review": GradePolicy(
        activity_type="srs_review",
        grade_source="direct_button",
        grade_mapping=MappingProxyType({1: 1, 2: 2, 3: 3, 4: 4}),
        description="SRS review grade (recall-based: Again/Hard/Good/Easy)",
    ),
    "first_exposure": GradePolicy(
        activity_type="first_exposure",
        grade_source="direct_button",
        grade_mapping=MappingProxyType({1: 1, 2: 2, 3: 3, 4: 4}),
        description="First-exposure grade (familiarity-based: Again/Hard/Good/Easy)",
    ),
    "new_ai_card": GradePolicy(
        activity_type="new_ai_card",
        grade_source="ai_judgment",
        grade_mapping=MappingProxyType({1: 1, 2: 2, 3: 3, 4: 4}),
        description="AI-generated card initial exposure",
    ),
    "ai_quiz": GradePolicy(
        activity_type="ai_quiz",
        grade_source="ai_judgment",
        grade_mapping=MappingProxyType({
            "incorrect": 1,
            "partial": 2,
            "correct": 3,
            "perfect": 4,
        }),
        description="AI quiz scoring (incorrect/partial/correct/perfect)",
    ),
    "sentence_write": GradePolicy(
        activity_type="sentence_write",
        grade_source="ai_judgment",
        grade_mapping=MappingProxyType({
            "incorrect": 1,
            "partial": 2,
            "correct": 3,
            "perfect": 4,
        }),
        description="Sentence writing assessment (judged by AI)",
    ),
}


def resolve_grade(activity_type: str, source_value: Any) -> int:
    if activity_type not in GRADE_POLICIES:
        raise ValueError(f"Unknown activity_type: {activity_type!r}")
    policy = GRADE_POLICIES[activity_type]
    return policy.grade_mapping[source_value]
