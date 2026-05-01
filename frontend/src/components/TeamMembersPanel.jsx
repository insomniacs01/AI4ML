import { useEffect, useState } from "react";

const ROLE_LABELS = {
  team_owner: "团队所有者",
  admin: "管理员",
  business_user: "业务成员",
  developer_user: "开发成员",
  member: "成员",
};

const STATUS_LABELS = {
  invited: "已邀请",
  active: "正常",
  frozen: "已冻结",
  removed: "已移除",
};

const ROLE_OPTIONS = ["team_owner", "admin", "business_user", "developer_user", "member"];
const STATUS_OPTIONS = ["invited", "active", "frozen", "removed"];

function formatRole(role) {
  return ROLE_LABELS[role] ?? role;
}

function formatStatus(status) {
  return STATUS_LABELS[status] ?? status;
}

function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function TeamMembersPanel({
  activeTeam,
  memberships,
  teamMembers,
  loading,
  activeUserId,
  canManage,
  inviteBusy,
  roleUpdatingUserId,
  statusUpdatingUserId,
  inviteInfo,
  onRefresh,
  onSelectTeam,
  onPrepareInvite,
  onUpdateRole,
  onUpdateStatus,
}) {
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteNote, setInviteNote] = useState("");
  const [roleDrafts, setRoleDrafts] = useState({});
  const [statusDrafts, setStatusDrafts] = useState({});

  useEffect(() => {
    setRoleDrafts(
      Object.fromEntries(
        (Array.isArray(teamMembers) ? teamMembers : []).map((member) => [member.user_id, member.role]),
      ),
    );
    setStatusDrafts(
      Object.fromEntries(
        (Array.isArray(teamMembers) ? teamMembers : []).map((member) => [member.user_id, member.member_status ?? "active"]),
      ),
    );
  }, [teamMembers]);

  return (
    <div className="detail-stack team-page-layout">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>当前团队</h3>
            <p>这里集中显示团队邀请码、你的角色，以及成员治理入口。</p>
          </div>
          <div className="section-actions">
            <button type="button" className="ghost-button" onClick={onRefresh}>
              刷新成员
            </button>
          </div>
        </div>

        {activeTeam ? (
          <div className="summary-grid">
            <article className="summary-item"><span>团队名称</span><strong>{activeTeam.name}</strong></article>
            <article className="summary-item"><span>我的角色</span><strong>{formatRole(activeTeam.role)}</strong></article>
            <article className="summary-item"><span>邀请码</span><strong>{activeTeam.invite_code}</strong></article>
            <article className="summary-item"><span>加入时间</span><strong>{formatDateTime(activeTeam.joined_at ?? activeTeam.created_at)}</strong></article>
          </div>
        ) : (
          <div className="empty-state">当前还没有选中团队。</div>
        )}
      </section>

      {memberships.length > 1 ? (
        <section className="section-card">
          <div className="section-head">
            <div>
              <h3>我的团队</h3>
              <p>切换团队后，任务、连接器、配额和默认 AI 路由都会同步切换。</p>
            </div>
          </div>
          <div className="task-cards">
            {memberships.map((membership) => (
              <button
                key={membership.id}
                type="button"
                className={membership.id === activeTeam?.id ? "task-card task-card-button selected" : "task-card task-card-button"}
                onClick={() => onSelectTeam(membership.id)}
              >
                <div className="task-card-top">
                  <h4>{membership.name}</h4>
                  <span>{formatRole(membership.role)}</span>
                </div>
                <p>邀请码：{membership.invite_code}</p>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>邀请成员</h3>
            <p>当前版本沿用邀请码入队。这里会返回团队邀请码和可直接转发的分享文案。</p>
          </div>
        </div>

        <form
          className="task-form"
          onSubmit={(event) => {
            event.preventDefault();
            onPrepareInvite?.({ email: inviteEmail.trim() || null, note: inviteNote.trim() || null });
          }}
        >
          <div className="form-row">
            <label className="field">
              <span>成员邮箱（可选）</span>
              <input value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} placeholder="仅用于生成更明确的分享文案" />
            </label>
            <label className="field">
              <span>备注（可选）</span>
              <input value={inviteNote} onChange={(event) => setInviteNote(event.target.value)} placeholder="例如：给模型评审同学加入团队" />
            </label>
          </div>
          <div className="button-row">
            <button type="submit" className="primary-button" disabled={!canManage || inviteBusy}>
              {inviteBusy ? "准备中..." : "生成邀请信息"}
            </button>
          </div>
        </form>

        {inviteInfo ? (
          <div className="callout">
            <strong>邀请码：{inviteInfo.invite_code}</strong>
            <p>{inviteInfo.share_text}</p>
          </div>
        ) : null}
      </section>

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>团队成员</h3>
            <p>管理员可以在这里同时维护成员角色和成员状态。开发相关页面会按角色严格收口。</p>
          </div>
        </div>

        {loading && !teamMembers.length ? <p className="meta-note">正在读取团队成员...</p> : null}

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>名称</th>
                <th>邮箱</th>
                <th>角色</th>
                <th>状态</th>
                <th>加入时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {teamMembers.length ? (
                teamMembers.map((member) => {
                  const isCurrentUser = member.user_id === activeUserId;
                  return (
                    <tr key={`${member.user_id}-${member.team_id}`}>
                      <td>
                        <div className="table-cell-stack">
                          <strong>{member.profile?.display_name ?? "未命名用户"}</strong>
                          {isCurrentUser ? <span>当前账号</span> : null}
                        </div>
                      </td>
                      <td>{member.profile?.email ?? "-"}</td>
                      <td>{formatRole(member.role)}</td>
                      <td>{formatStatus(member.member_status)}</td>
                      <td>{formatDateTime(member.joined_at)}</td>
                      <td>
                        {canManage ? (
                          <div className="detail-stack">
                            <div className="button-row">
                              <select
                                value={roleDrafts[member.user_id] ?? member.role}
                                onChange={(event) => setRoleDrafts((current) => ({ ...current, [member.user_id]: event.target.value }))}
                                disabled={isCurrentUser}
                              >
                                {ROLE_OPTIONS.map((option) => (
                                  <option key={option} value={option}>
                                    {option}
                                  </option>
                                ))}
                              </select>
                              <button
                                type="button"
                                className="ghost-button"
                                disabled={isCurrentUser || roleUpdatingUserId === member.user_id}
                                onClick={() => onUpdateRole?.(member.user_id, { role: roleDrafts[member.user_id] ?? member.role })}
                              >
                                {roleUpdatingUserId === member.user_id ? "保存中..." : "保存角色"}
                              </button>
                            </div>

                            <div className="button-row">
                              <select
                                value={statusDrafts[member.user_id] ?? member.member_status ?? "active"}
                                onChange={(event) => setStatusDrafts((current) => ({ ...current, [member.user_id]: event.target.value }))}
                                disabled={isCurrentUser}
                              >
                                {STATUS_OPTIONS.map((option) => (
                                  <option key={option} value={option}>
                                    {option}
                                  </option>
                                ))}
                              </select>
                              <button
                                type="button"
                                className="ghost-button"
                                disabled={isCurrentUser || statusUpdatingUserId === member.user_id}
                                onClick={() => onUpdateStatus?.(member.user_id, { member_status: statusDrafts[member.user_id] ?? member.member_status ?? "active" })}
                              >
                                {statusUpdatingUserId === member.user_id ? "保存中..." : "保存状态"}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <span className="meta-note">仅管理员可修改</span>
                        )}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={6}><div className="table-empty">当前团队还没有返回任何成员数据。</div></td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
