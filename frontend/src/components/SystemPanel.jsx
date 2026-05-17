const HEALTH_FIELDS = [
  ["后端状态", "status"],
  ["项目基座", "selected_project_base"],
  ["运行环境", "execution_runtime"],
  ["任务执行器", "task_executor"],
  ["执行模式", "execution_mode"],
  ["AI 服务模式", "provider_mode"],
  ["AI 服务状态", "provider_status"],
  ["AI 服务详情", "provider_detail"],
  ["执行器状态", "executor_status"],
  ["执行器详情", "executor_detail"],
  ["Base URL", "provider_base_url"],
  ["接口类型", "provider_wire_api"],
  ["模型别名", "model_alias"],
  ["任务存储目录", "storage_dir"],
  ["运行输出目录", "run_output_dir"],
];

export default function SystemPanel({ health, loading, error, onRefresh }) {
  return (
    <section className="section-card system-panel-card">
      <div className="section-head">
        <div>
          <p className="eyebrow">Health</p>
          <h3>系统状态</h3>
          <p>这里能看出后端服务和当前 AI 服务是否可用。</p>
        </div>
        <div className="section-actions">
          <button type="button" className="ghost-button" onClick={onRefresh} disabled={loading}>
            {loading ? "刷新中..." : "刷新状态"}
          </button>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}

      {health ? (
        <div className="summary-grid">
          {HEALTH_FIELDS.map(([label, key]) => (
            <article key={key} className="summary-item">
              <span>{label}</span>
              <strong>{health[key] ?? "暂无"}</strong>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">后端健康信息暂时还没有读取成功。</div>
      )}
    </section>
  );
}
