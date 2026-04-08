function formatMetric(task) {
  if (!task.last_run) {
    return "No run yet";
  }
  return `${task.last_run.metric_name}: ${task.last_run.metric_value.toFixed(4)}`;
}

export default function TaskCard({ task, onRun, running }) {
  return (
    <article className="task-card">
      <div className="task-card-top">
        <div>
          <p className="eyebrow">Task {task.id}</p>
          <h3>{task.name}</h3>
        </div>
        <span className={`status status-${task.status}`}>{task.status}</span>
      </div>
      <p className="task-description">{task.description}</p>
      <dl className="task-meta">
        <div>
          <dt>target</dt>
          <dd>{task.label_column}</dd>
        </div>
        <div>
          <dt>problem</dt>
          <dd>{task.problem_type}</dd>
        </div>
        <div>
          <dt>dataset</dt>
          <dd>{task.dataset_filename ?? "not uploaded"}</dd>
        </div>
        <div>
          <dt>latest</dt>
          <dd>{formatMetric(task)}</dd>
        </div>
      </dl>
      {task.last_run ? (
        <div className="run-summary">
          <strong>Best result</strong>
          <span>{task.last_run.best_model}</span>
        </div>
      ) : null}
      <button
        type="button"
        className="secondary"
        onClick={() => onRun(task.id)}
        disabled={!task.dataset_path || running}
      >
        {running ? "Running..." : "Run MLZero validation"}
      </button>
      {task.notes ? <p className="muted">{task.notes}</p> : null}
    </article>
  );
}
