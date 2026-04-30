const HEALTH_FIELDS = [
  ["后端状态", "status"],
  ["项目基座", "selected_project_base"],
  ["运行时", "execution_runtime"],
  ["任务执行器", "task_executor"],
  ["执行模式", "execution_mode"],
  ["提供方模式", "provider_mode"],
  ["Provider 状态", "provider_status"],
  ["Provider 详情", "provider_detail"],
  ["Executor 状态", "executor_status"],
  ["Executor 详情", "executor_detail"],
  ["Base URL", "provider_base_url"],
  ["Wire API", "provider_wire_api"],
  ["模型别名", "model_alias"],
  ["任务存储目录", "storage_dir"],
  ["运行输出目录", "run_output_dir"],
];

export default function SystemPanel({ health, loading, error, onRefresh }) {
  return (
    <section className="section-card">
      <div className="section-head">
        <div>
          <p className="eyebrow">Health</p>
          <h3>后端与运行时状态</h3>
          <p>这里能看出当前运行时是否真的可用，以及任务解析和 MLZero 会走哪套 provider 配置。</p>
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
