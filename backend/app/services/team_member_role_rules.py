from __future__ import annotations


TEAM_OWNER_ROLE = "team_owner"


def assert_member_role_update_allowed(
    *,
    target_member_id: str,
    requested_role: object,
    actor_user_id: str,
    actor_role: object,
) -> None:
    if role_value(requested_role) == TEAM_OWNER_ROLE:
        raise ValueError("team_owner must be assigned through the ownership transfer endpoint.")
    if target_member_id == actor_user_id and role_value(actor_role) == TEAM_OWNER_ROLE:
        raise ValueError("team_owner cannot demote themselves through member role update. Use ownership transfer instead.")


def role_value(value: object) -> str:
    return str(value.value if hasattr(value, "value") else value or "").strip()
