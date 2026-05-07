import { useEffect, useState } from "react";

function formatToken(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN") : "0";
}

function getQuotaKey(item) {
  return `${item.scope_type ?? "member"}:${item.scope_key || item.user_id || item.connector_id || item.team_id}`;
}

function getQuotaTitle(item) {
  if (item.scope_type === "team") return "团队总额度";
  if (item.scope_type === "connector") return item.connector_display_name || item.connector_id || item.scope_key;
  return item.display_name || item.email || item.user_id || item.scope_key;
}

function getQuotaSubtitle(item) {
  if (item.scope_type === "team") return item.team_id;
  if (item.scope_type === "connector") return item.connector_id || item.scope_key;
  return item.email || item.user_id || item.scope_key;
}

function getQuotaScopeLabel(scopeType) {
  if (scopeType === "team") return "团队";
  if (scopeType === "connector") return "连接器";
  return "成员";
}

export default function QuotaManagementPanel({
  quotas,
  loading,
  savingQuotaKey,
  message,
  error,
  onRefresh,
  onSave,
}) {
  const [drafts, setDrafts] = useState({});

  useEffect(() => {
    setDrafts(
      Object.fromEntries(
        (Array.isArray(quotas) ? quotas : []).map((item) => [
          getQuotaKey(item),
          {
            token_quota: String(item.token_quota ?? 0),
            warning_threshold: String(item.warning_threshold ?? 0),
            status: item.status ?? "active",
          },
        ]),
      ),
    );
  }, [quotas]);

  return (
    <div className="detail-stack quota-page-layout">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>配额账户</h3>
            <p>按团队、成员、连接器三个作用域维护真实 token 额度。冻结或耗尽的账户会被后端拦截。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新配额"}
          </button>
        </div>

        {message ? <div className="notice-banner">{message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        {!quotas?.length && !loading ? <div className="empty-state">当前团队还没有配额账户。</div> : null}

        {Array.isArray(quotas) && quotas.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>作用域</th>
                  <th>账户</th>
                  <th>角色/状态</th>
                  <th>已用</th>
                  <th>总额</th>
                  <th>剩余</th>
                  <th>账户状态</th>
                  <th>预警阈值</th>
                  <th>调整</th>
                </tr>
              </thead>
              <tbody>
                {quotas.map((item) => {
                  const quotaKey = getQuotaKey(item);
                  const draft = drafts[quotaKey] ?? { token_quota: "0", warning_threshold: "0", status: item.status ?? "active" };
                  return (
                    <tr key={quotaKey}>
                      <td>{getQuotaScopeLabel(item.scope_type)}</td>
                      <td>
                        <div className="table-cell-stack">
                          <strong>{getQuotaTitle(item)}</strong>
                          <span>{getQuotaSubtitle(item)}</span>
                        </div>
                      </td>
                      <td>{[item.role, item.member_status].filter(Boolean).join(" / ") || "-"}</td>
                      <td>{formatToken(item.token_used)}</td>
                      <td>{formatToken(item.token_quota)}</td>
                      <td>{formatToken(item.token_remaining)}</td>
                      <td>{item.status}</td>
                      <td>{formatToken(item.warning_threshold)}</td>
                      <td>
                        <div className="detail-stack">
                          <div className="button-row">
                            <input
                              value={draft.token_quota}
                              onChange={(event) => setDrafts((current) => ({
                                ...current,
                                [quotaKey]: { ...draft, token_quota: event.target.value },
                              }))}
                              className="quota-input"
                              placeholder="总额"
                            />
                            <input
                              value={draft.warning_threshold}
                              onChange={(event) => setDrafts((current) => ({
                                ...current,
                                [quotaKey]: { ...draft, warning_threshold: event.target.value },
                              }))}
                              className="quota-input"
                              placeholder="阈值"
                            />
                          </div>

                          <div className="button-row">
                            <select
                              value={draft.status}
                              onChange={(event) => setDrafts((current) => ({
                                ...current,
                                [quotaKey]: { ...draft, status: event.target.value },
                              }))}
                            >
                              <option value="active">active</option>
                              <option value="frozen">frozen</option>
                              <option value="exhausted">exhausted</option>
                            </select>
                            <button
                              type="button"
                              className="ghost-button"
                              disabled={savingQuotaKey === quotaKey}
                              onClick={() => onSave?.(item, {
                                token_quota: Number.parseInt(draft.token_quota || "0", 10) || 0,
                                warning_threshold: Number.parseInt(draft.warning_threshold || "0", 10) || 0,
                                status: draft.status,
                              })}
                            >
                              {savingQuotaKey === quotaKey ? "保存中..." : "保存"}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
