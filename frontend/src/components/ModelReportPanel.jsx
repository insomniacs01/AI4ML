import LeaderboardPanel from "./LeaderboardPanel.jsx";

function formatDateTime(value) {
  if (!value) return "暂无";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

function formatMetricValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(4);
}

function formatConfidence(value) {
  return typeof value === "number" && !Number.isNaN(value) ? `${Math.round(value * 100)}%` : "暂无";
}

export default function ModelReportPanel({
  tasks,
  selectedTask,
  onSelectTask,
  formatMetricName,
}) {
  const analysis = selectedTask?.structured_requirements && typeof selectedTask.structured_requirements === "object"
    ? selectedTask.structured_requirements
    : null;

  return (
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>选择任务</h3>
            <p>模型报告页只展示真实已经写回任务记录的分析与运行结果。</p>
          </div>
        </div>

        {!tasks?.length ? <div className="empty-state">当前没有可展示报告的任务。</div> : null}

        {Array.isArray(tasks) && tasks.length ? (
          <div className="task-cards">
            {tasks.map((task) => (
              <button
                key={task.id}
                type="button"
                className={task.id === selectedTask?.id ? "task-card task-card-button selected" : "task-card task-card-button"}
                onClick={() => onSelectTask?.(task.id)}
              >
                <div className="task-card-top">
                  <h4>{task.name}</h4>
                  <span>{task.last_run ? "已产出结果" : "暂无结果"}</span>
                </div>
                <p>{task.dataset_filename || "未上传数据集"}</p>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {!selectedTask ? <div className="empty-state">先选择一个任务，再查看模型报告。</div> : null}

      {selectedTask ? (
        <>
          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>任务概览</h3>
                <p>报告页会把任务语义、AI 分析和 MLZero 成功结果放在一起看。</p>
              </div>
            </div>

            <div className="summary-grid">
              <article className="summary-item"><span>任务名称</span><strong>{selectedTask.name}</strong></article>
              <article className="summary-item"><span>数据集</span><strong>{selectedTask.dataset_filename || "未上传"}</strong></article>
              <article className="summary-item"><span>目标列</span><strong>{selectedTask.label_column || "未解析"}</strong></article>
              <article className="summary-item"><span>任务类型</span><strong>{selectedTask.problem_type || "未解析"}</strong></article>
              <article className="summary-item"><span>建议指标</span><strong>{formatMetricName(analysis?.metric_name || selectedTask.last_run?.metric_name)}</strong></article>
              <article className="summary-item"><span>AI 置信度</span><strong>{formatConfidence(analysis?.confidence)}</strong></article>
            </div>
          </section>

          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>AI 解析结论</h3>
                <p>这里展示的是任务字段自动解析的理由和时间，不会伪造自然语言总结。</p>
              </div>
            </div>

            {analysis ? (
              <div className="detail-stack">
                <div className="summary-grid">
                  <article className="summary-item"><span>解析模型</span><strong>{analysis.analysis_model || "未记录"}</strong></article>
                  <article className="summary-item"><span>解析时间</span><strong>{formatDateTime(analysis.analyzed_at)}</strong></article>
                  <article className="summary-item"><span>列数量</span><strong>{Array.isArray(analysis.column_names) ? analysis.column_names.length : 0}</strong></article>
                  <article className="summary-item"><span>预览行数</span><strong>{Array.isArray(analysis.preview_rows) ? analysis.preview_rows.length : 0}</strong></article>
                </div>
                <div className="callout">
                  <strong>AI 推断理由</strong>
                  <p>{analysis.reasoning || "暂无推断理由。"}</p>
                </div>
              </div>
            ) : (
              <div className="empty-state">这个任务还没有 AI 解析记录。</div>
            )}
          </section>

          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>MLZero 结果摘要</h3>
                <p>这里只展示已经真实完成的最近一次成功结果。</p>
              </div>
            </div>

            {selectedTask.last_run ? (
              <div className="summary-grid">
                <article className="summary-item"><span>最佳模型</span><strong>{selectedTask.last_run.best_model}</strong></article>
                <article className="summary-item"><span>指标名称</span><strong>{formatMetricName(selectedTask.last_run.metric_name)}</strong></article>
                <article className="summary-item"><span>指标数值</span><strong>{formatMetricValue(selectedTask.last_run.metric_value)}</strong></article>
                <article className="summary-item"><span>输出目录</span><strong className="mono-text">{selectedTask.last_run.output_dir}</strong></article>
              </div>
            ) : (
              <div className="empty-state">当前还没有成功运行结果，因此暂时无法生成模型报告摘要。</div>
            )}
          </section>

          {selectedTask.last_run ? (
            <LeaderboardPanel
              run={selectedTask.last_run}
              formatMetricName={formatMetricName}
              formatMetricValue={formatMetricValue}
            />
          ) : null}
        </>
      ) : null}
    </div>
  );
}
