export default function SystemPanel({ health }) {
  return (
    <section className="panel">
      <div className="panel-header">
        <div>
          <p className="eyebrow">Backend Health</p>
          <h2>Execution runtime</h2>
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
        </div>
      ) : (
        <p className="muted">Backend not connected yet.</p>
      )}
    </section>
  );
}
