import { useEffect, useState } from "react";

function formatToken(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString("zh-CN") : "0";
}

export default function QuotaManagementPanel({
  quotas,
  loading,
  savingMemberId,
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
          item.user_id,
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
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>成员配额</h3>
            <p>这里的配额会直接影响 AI 解析、任务对话和 MLZero 运行。冻结或耗尽的成员会被后端拦截。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新配额"}
          </button>
        </div>

        {message ? <div className="notice-banner">{message}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        {!quotas?.length && !loading ? <div className="empty-state">当前团队还没有成员配额数据。</div> : null}

        {Array.isArray(quotas) && quotas.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>成员</th>
                  <th>角色</th>
                  <th>成员状态</th>
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
                  const draft = drafts[item.user_id] ?? { token_quota: "0", warning_threshold: "0", status: item.status ?? "active" };
                  return (
                    <tr key={item.user_id}>
                      <td>
                        <div className="table-cell-stack">
                          <strong>{item.display_name || item.email || item.user_id}</strong>
                          <span>{item.email || item.user_id}</span>
                        </div>
                      </td>
                      <td>{item.role}</td>
                      <td>{item.member_status}</td>
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
                                [item.user_id]: { ...draft, token_quota: event.target.value },
                              }))}
                              className="quota-input"
                              placeholder="总额"
                            />
                            <input
                              value={draft.warning_threshold}
                              onChange={(event) => setDrafts((current) => ({
                                ...current,
                                [item.user_id]: { ...draft, warning_threshold: event.target.value },
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
                                [item.user_id]: { ...draft, status: event.target.value },
                              }))}
                            >
                              <option value="active">active</option>
                              <option value="frozen">frozen</option>
                              <option value="exhausted">exhausted</option>
                            </select>
                            <button
                              type="button"
                              className="ghost-button"
                              disabled={savingMemberId === item.user_id}
                              onClick={() => onSave?.(item.user_id, {
                                token_quota: Number.parseInt(draft.token_quota || "0", 10) || 0,
                                warning_threshold: Number.parseInt(draft.warning_threshold || "0", 10) || 0,
                                status: draft.status,
                              })}
                            >
                              {savingMemberId === item.user_id ? "保存中..." : "保存"}
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
