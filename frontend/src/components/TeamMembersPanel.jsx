import { useEffect, useMemo, useState } from "react";

const ROLE_LABELS = {
  team_owner: "团队所有者",
  admin: "管理员",
  business_user: "业务成员",
  developer_user: "开发成员",
  member: "成员",
};

const MEMBER_STATUS_LABELS = {
  invited: "已邀请",
  active: "正常",
  frozen: "已冻结",
  removed: "已移除",
};

const TEAM_STATUS_LABELS = {
  active: "正常",
  disabled: "已停用",
  archived: "已归档",
};

const ROLE_OPTIONS = ["admin", "business_user", "developer_user", "member"];
const MEMBER_STATUS_OPTIONS = ["invited", "active", "frozen", "removed"];
const TEAM_STATUS_OPTIONS = ["active", "disabled", "archived"];

function formatRole(role) {
  return ROLE_LABELS[role] ?? role;
}

function formatMemberStatus(status) {
  return MEMBER_STATUS_LABELS[status] ?? status;
}

function formatTeamStatus(status) {
  return TEAM_STATUS_LABELS[status] ?? status;
}

function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatMemberLabel(member) {
  return member?.profile?.display_name || member?.profile?.email || member?.user_id || "未命名成员";
}

export default function TeamMembersPanel({
  activeTeam,
  memberships,
  teamMembers,
  teamSettings,
  teamSettingsLoading,
  teamSettingsSaving,
  ownershipTransferring,
  loading,
  activeUserId,
  canManage,
  canOwn,
  inviteBusy,
  roleUpdatingUserId,
  statusUpdatingUserId,
  inviteInfo,
  onRefresh,
  onSelectTeam,
  onPrepareInvite,
  onUpdateRole,
  onUpdateStatus,
  onUpdateSettings,
  onTransferOwnership,
}) {
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteNote, setInviteNote] = useState("");
  const [roleDrafts, setRoleDrafts] = useState({});
  const [statusDrafts, setStatusDrafts] = useState({});
  const [settingsDraft, setSettingsDraft] = useState({ name: "", description: "", status: "active" });
  const [transferTarget, setTransferTarget] = useState("");

  const ownerUserId = teamSettings?.owner_user_id || activeTeam?.created_by || "";
  const activeMembers = useMemo(
    () => (Array.isArray(teamMembers) ? teamMembers : []).filter((member) => member.member_status === "active"),
    [teamMembers],
  );
  const ownerCandidates = useMemo(
    () => activeMembers.filter((member) => member.user_id !== ownerUserId),
    [activeMembers, ownerUserId],
  );

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

  useEffect(() => {
    const source = teamSettings || activeTeam || {};
    setSettingsDraft({
      name: source.name ?? "",
      description: source.description ?? "",
      status: source.status ?? "active",
    });
  }, [activeTeam, teamSettings]);

  useEffect(() => {
    setTransferTarget(ownerCandidates[0]?.user_id ?? "");
  }, [ownerCandidates]);

  async function handleSettingsSubmit(event) {
    event.preventDefault();
    const ok = await onUpdateSettings?.({
      name: settingsDraft.name.trim(),
      description: settingsDraft.description.trim() || null,
      status: settingsDraft.status,
    });
    if (ok === false) return;
  }

  async function handleTransferSubmit(event) {
    event.preventDefault();
    if (!transferTarget) return;
    const ok = await onTransferOwnership?.(transferTarget);
    if (ok !== false) setTransferTarget("");
  }

  return (
    <div className="detail-stack team-page-layout">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>当前团队</h3>
            <p>这里集中显示团队邀请码、你的角色、团队状态，以及成员治理入口。</p>
          </div>
          <div className="section-actions">
            <button type="button" className="ghost-button" onClick={onRefresh}>
              刷新团队
            </button>
          </div>
        </div>

        {activeTeam ? (
          <div className="summary-grid">
            <article className="summary-item"><span>团队名称</span><strong>{activeTeam.name}</strong></article>
            <article className="summary-item"><span>我的角色</span><strong>{formatRole(activeTeam.role)}</strong></article>
            <article className="summary-item"><span>团队状态</span><strong>{formatTeamStatus(teamSettings?.status ?? activeTeam.status)}</strong></article>
            <article className="summary-item"><span>邀请码</span><strong>{activeTeam.invite_code}</strong></article>
            <article className="summary-item"><span>团队所有者</span><strong>{teamSettings?.owner_display_name || teamSettings?.owner_email || ownerUserId || "未记录"}</strong></article>
            <article className="summary-item"><span>加入时间</span><strong>{formatDateTime(activeTeam.joined_at ?? activeTeam.created_at)}</strong></article>
          </div>
        ) : (
          <div className="empty-state">当前还没有选中团队。</div>
        )}
      </section>

      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>团队设置</h3>
            <p>团队所有者可以维护团队基础信息、停用或归档团队，并把所有权转移给其他活跃成员。</p>
          </div>
          {teamSettingsLoading ? <span className="runtime-pill warning">读取中</span> : <span className="runtime-pill info">Owner only</span>}
        </div>

        <form className="task-form" onSubmit={handleSettingsSubmit}>
          <div className="form-row">
            <label className="field">
              <span>团队名称</span>
              <input
                value={settingsDraft.name}
                onChange={(event) => setSettingsDraft((current) => ({ ...current, name: event.target.value }))}
                maxLength={120}
                disabled={!canOwn || teamSettingsSaving}
                required
              />
            </label>
            <label className="field">
              <span>团队状态</span>
              <select
                value={settingsDraft.status}
                onChange={(event) => setSettingsDraft((current) => ({ ...current, status: event.target.value }))}
                disabled={!canOwn || teamSettingsSaving}
              >
                {TEAM_STATUS_OPTIONS.map((option) => (
                  <option key={option} value={option}>{formatTeamStatus(option)}</option>
                ))}
              </select>
            </label>
          </div>

          <label className="field">
            <span>团队说明</span>
            <textarea
              rows={3}
              value={settingsDraft.description}
              onChange={(event) => setSettingsDraft((current) => ({ ...current, description: event.target.value }))}
              maxLength={2000}
              disabled={!canOwn || teamSettingsSaving}
              placeholder="记录团队用途、课程分组或项目边界。"
            />
          </label>

          <div className="button-row connector-actions">
            <button type="submit" className="primary-button" disabled={!canOwn || teamSettingsSaving || teamSettingsLoading}>
              {teamSettingsSaving ? "保存中..." : "保存团队设置"}
            </button>
            {!canOwn ? <span className="helper-text">只有团队所有者可以修改团队设置。</span> : null}
          </div>
        </form>

        <form className="task-form owner-transfer-form" onSubmit={handleTransferSubmit}>
          <div className="section-head compact-section-head">
            <div>
              <h3>所有权转移</h3>
              <p>转移后，新的所有者获得团队设置和所有权治理权限，当前所有者会降为管理员。</p>
            </div>
          </div>
          <div className="form-row">
            <label className="field">
              <span>新团队所有者</span>
              <select
                value={transferTarget}
                onChange={(event) => setTransferTarget(event.target.value)}
                disabled={!canOwn || ownershipTransferring || !ownerCandidates.length}
              >
                {ownerCandidates.length ? ownerCandidates.map((member) => (
                  <option key={member.user_id} value={member.user_id}>
                    {formatMemberLabel(member)}
                  </option>
                )) : <option value="">没有可转移的活跃成员</option>}
              </select>
            </label>
            <div className="field owner-transfer-action">
              <span>操作</span>
              <button type="submit" className="danger-button" disabled={!canOwn || ownershipTransferring || !transferTarget}>
                {ownershipTransferring ? "转移中..." : "转移所有权"}
              </button>
            </div>
          </div>
        </form>
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
            <p>管理员可以维护成员角色和成员状态；团队所有者身份通过上方“所有权转移”单独治理。</p>
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
                  const isOwner = member.role === "team_owner";
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
                      <td>{formatMemberStatus(member.member_status)}</td>
                      <td>{formatDateTime(member.joined_at)}</td>
                      <td>
                        {canManage ? (
                          <div className="detail-stack">
                            {isOwner ? (
                              <span className="meta-note">团队所有者请通过所有权转移变更。</span>
                            ) : (
                              <div className="button-row">
                                <select
                                  value={roleDrafts[member.user_id] ?? member.role}
                                  onChange={(event) => setRoleDrafts((current) => ({ ...current, [member.user_id]: event.target.value }))}
                                  disabled={isCurrentUser}
                                >
                                  {ROLE_OPTIONS.map((option) => (
                                    <option key={option} value={option}>
                                      {formatRole(option)}
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
                            )}

                            <div className="button-row">
                              <select
                                value={statusDrafts[member.user_id] ?? member.member_status ?? "active"}
                                onChange={(event) => setStatusDrafts((current) => ({ ...current, [member.user_id]: event.target.value }))}
                                disabled={isCurrentUser || isOwner}
                              >
                                {MEMBER_STATUS_OPTIONS.map((option) => (
                                  <option key={option} value={option}>
                                    {formatMemberStatus(option)}
                                  </option>
                                ))}
                              </select>
                              <button
                                type="button"
                                className="ghost-button"
                                disabled={isCurrentUser || isOwner || statusUpdatingUserId === member.user_id}
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
