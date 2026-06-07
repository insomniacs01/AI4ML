from __future__ import annotations

import pytest

from backend.app.models.governance import TeamMemberRecord
from backend.app.services.governance_team_ownership import resolve_ownership_transfer


def _member(
    user_id: str,
    *,
    role: str = "member",
    member_status: str = "active",
) -> TeamMemberRecord:
    return TeamMemberRecord(
        team_id="team-1",
        user_id=user_id,
        role=role,
        member_status=member_status,
    )


def test_resolve_ownership_transfer_returns_previous_and_next_owner() -> None:
    previous_owner = _member("owner-1", role="team_owner")
    next_owner = _member("user-1")

    plan = resolve_ownership_transfer(
        [previous_owner, next_owner],
        current_owner_id="owner-1",
        new_owner_user_id="user-1",
    )

    assert plan.previous_owner == previous_owner
    assert plan.next_owner == next_owner
    assert not plan.is_noop


def test_resolve_ownership_transfer_detects_noop_owner_transfer() -> None:
    previous_owner = _member("owner-1", role="team_owner")

    plan = resolve_ownership_transfer(
        [previous_owner],
        current_owner_id="owner-1",
        new_owner_user_id="owner-1",
    )

    assert plan.previous_owner == previous_owner
    assert plan.next_owner == previous_owner
    assert plan.is_noop


def test_resolve_ownership_transfer_rejects_non_owner_actor() -> None:
    with pytest.raises(PermissionError, match="current team owner"):
        resolve_ownership_transfer(
            [_member("user-1")],
            current_owner_id="user-1",
            new_owner_user_id="user-2",
        )


def test_resolve_ownership_transfer_rejects_missing_next_owner() -> None:
    with pytest.raises(ValueError, match="not a member"):
        resolve_ownership_transfer(
            [_member("owner-1", role="team_owner")],
            current_owner_id="owner-1",
            new_owner_user_id="missing-user",
        )


def test_resolve_ownership_transfer_rejects_inactive_next_owner() -> None:
    with pytest.raises(ValueError, match="active team member"):
        resolve_ownership_transfer(
            [
                _member("owner-1", role="team_owner"),
                _member("user-1", member_status="frozen"),
            ],
            current_owner_id="owner-1",
            new_owner_user_id="user-1",
        )
