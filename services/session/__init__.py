"""Session engine package — public API and SessionNode dataclass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionNode:
    activity_type: str
    source_tier: int
    card_data: dict
    source_id: int | None = None
    activity_meta: dict = field(default_factory=dict)
    grade_policy_ref: str | None = None
    interaction_schema: dict | None = None


from services.session.grade_policy import (  # noqa: E402
    ACTIVITY_REGISTRY,
    GRADE_POLICIES,
    ActivityHandler,
    GradePolicy,
    resolve_grade,
)

from services.session.assembly import (  # noqa: E402
    build_session,
    build_session_list,
    generate_tier3_node,
)


__all__ = [
    "ACTIVITY_REGISTRY",
    "GRADE_POLICIES",
    "ActivityHandler",
    "GradePolicy",
    "SessionNode",
    "build_session",
    "build_session_list",
    "generate_tier3_node",
    "resolve_grade",
]
