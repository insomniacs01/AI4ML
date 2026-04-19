export default function SystemPanel({ health }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">系统状态面板</p>
          <h2>健康检查与运行环境</h2>
        </div>
      </div>
      {health ? (
        <div className="health-grid">
          <div>
            <span className="meta-label">status</span>
            <strong>{health.status}</strong>
          </div>
          <div>
            <span className="meta-label">selected base</span>
            <strong>{health.selected_project_base}</strong>
          </div>
          <div>
            <span className="meta-label">runtime</span>
            <strong>{health.execution_runtime}</strong>
          </div>
          <div>
            <span className="meta-label">llm mode</span>
            <strong>{health.llm_mode ?? "local"}</strong>
          </div>
          <div>
            <span className="meta-label">llm provider</span>
            <strong>{health.llm_provider ?? "openai"}</strong>
          </div>
          <div>
            <span className="meta-label">llm model</span>
            <strong>{health.llm_model ?? health.model_alias}</strong>
          </div>
          <div>
            <span className="meta-label">provider</span>
            <strong>{health.provider_base_url}</strong>
          </div>
          <div>
            <span className="meta-label">model alias</span>
            <strong>{health.model_alias}</strong>
          </div>
          <div>
            <span className="meta-label">task storage</span>
            <strong>{health.storage_dir}</strong>
          </div>
          <div>
            <span className="meta-label">run output</span>
            <strong>{health.run_output_dir}</strong>
          </div>
          <div>
            <span className="meta-label">mlzero config</span>
            <strong>{health.mlzero_config_path ?? "未提供"}</strong>
          </div>
        </div>
      ) : (
        <p className="muted">后端暂未连接。</p>
      )}
    </section>
  );
}
