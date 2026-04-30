function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

export default function AuditLogPanel({
  logs,
  loading,
  error,
  onRefresh,
}) {
  return (
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>审计日志</h3>
            <p>这里展示团队范围内已经真实写入数据库的治理操作日志。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新日志"}
          </button>
        </div>

        {error ? <div className="error-banner">{error}</div> : null}
        {!logs?.length && !loading ? <div className="empty-state">当前团队还没有审计日志。</div> : null}

        {Array.isArray(logs) && logs.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>时间</th><th>操作者</th><th>动作</th><th>资源</th><th>详情</th></tr>
              </thead>
              <tbody>
                {logs.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{item.actor_display_name || item.actor_email || item.actor_id || "-"}</td>
                    <td>{item.action}</td>
                    <td>{item.resource_type ? `${item.resource_type}${item.resource_id ? ` / ${item.resource_id}` : ""}` : "-"}</td>
                    <td><code className="mono-text">{item.detail ? JSON.stringify(item.detail) : "-"}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </div>
  );
}
