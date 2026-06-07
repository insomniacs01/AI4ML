from __future__ import annotations

from backend.app.services.team_invite import build_team_invite_response


def test_build_team_invite_response_uses_email_hint() -> None:
    response = build_team_invite_response(
        team_id="team-1",
        team={"name": "AI4ML Team", "invite_code": "INVITE-123"},
        email="user@example.com",
    )

    assert response.team_id == "team-1"
    assert response.team_name == "AI4ML Team"
    assert response.invite_code == "INVITE-123"
    assert response.share_text == "团队“AI4ML Team”的邀请码是：INVITE-123。发送给 user@example.com。"
    assert response.detail == "邀请码已准备好，可以直接复制分享。"


def test_build_team_invite_response_defaults_team_name_and_copy_hint() -> None:
    response = build_team_invite_response(
        team_id="team-1",
        team={},
        email=None,
    )

    assert response.team_name == "team-1"
    assert response.invite_code == ""
    assert response.share_text == "团队“team-1”的邀请码是：。复制给需要加入团队的成员。"
