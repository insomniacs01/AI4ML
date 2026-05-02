from __future__ import annotations

from unittest import TestCase

from fastapi import HTTPException

from backend.app.core.supabase_auth import (
    SupabaseUser,
    TeamAccessContext,
    require_team_admin_access,
    require_team_developer_access,
    require_team_owner_access,
)


def _build_team_access(role: str) -> TeamAccessContext:
    return TeamAccessContext(
        team_id="team-1",
        role=role,
        user=SupabaseUser(id="user-1", email="user@example.com", raw={}),
        access_token="token",
    )


class TeamAccessRoleTests(TestCase):
    def test_team_admin_access_allows_admin(self) -> None:
        context = _build_team_access("admin")
        self.assertIs(require_team_admin_access(context), context)

    def test_team_admin_access_rejects_member(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            require_team_admin_access(_build_team_access("member"))
        self.assertEqual(raised.exception.status_code, 403)

    def test_team_developer_access_allows_developer_user(self) -> None:
        context = _build_team_access("developer_user")
        self.assertIs(require_team_developer_access(context), context)

    def test_team_developer_access_rejects_plain_member(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            require_team_developer_access(_build_team_access("member"))
        self.assertEqual(raised.exception.status_code, 403)

    def test_team_owner_access_allows_owner(self) -> None:
        context = _build_team_access("team_owner")
        self.assertIs(require_team_owner_access(context), context)

    def test_team_owner_access_rejects_admin(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            require_team_owner_access(_build_team_access("admin"))
        self.assertEqual(raised.exception.status_code, 403)
