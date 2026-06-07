from __future__ import annotations

from dataclasses import dataclass

from backend.app.models.governance import TeamMemberRecord


TEAM_OWNER_ROLE = "team_owner"
ACTIVE_MEMBER_STATUS = "active"


@dataclass(frozen=True)
class OwnershipTransferPlan:
    previous_owner: TeamMemberRecord
    next_owner: TeamMemberRecord

    @property
    def is_noop(self) -> bool:
        return self.previous_owner.user_id == self.next_owner.user_id


def resolve_ownership_transfer(
    members: list[TeamMemberRecord],
    *,
    current_owner_id: str,
    new_owner_user_id: str,
) -> OwnershipTransferPlan:
    previous_owner = next((item for item in members if item.user_id == current_owner_id), None)
    if previous_owner is None or previous_owner.role != TEAM_OWNER_ROLE:
        raise PermissionError("Only the current team owner can transfer ownership.")

    next_owner = next((item for item in members if item.user_id == new_owner_user_id), None)
    if next_owner is None:
        raise ValueError("new owner is not a member of this team")
    if next_owner.member_status != ACTIVE_MEMBER_STATUS:
        raise ValueError("new owner must be an active team member")

    return OwnershipTransferPlan(previous_owner=previous_owner, next_owner=next_owner)
