from __future__ import annotations

from typing import Mapping

from backend.app.models.governance import TeamInviteResponse


def build_team_invite_response(
    *,
    team_id: str,
    team: Mapping[str, object],
    email: str | None,
) -> TeamInviteResponse:
    team_name = str(team.get("name", team_id))
    invite_code = str(team.get("invite_code", ""))
    email_hint = f"发送给 {email}。" if email else "复制给需要加入团队的成员。"
    share_text = f"团队“{team_name}”的邀请码是：{invite_code}。{email_hint}"
    return TeamInviteResponse(
        team_id=team_id,
        team_name=team_name,
        invite_code=invite_code,
        share_text=share_text,
        detail="邀请码已准备好，可以直接复制分享。",
    )
