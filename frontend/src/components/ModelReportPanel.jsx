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

function formatPercent(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return `${Math.round(value * 1000) / 10}%`;
}

function getMissingTone(column) {
  if (!column?.missing_ratio) return "success";
  if (column.missing_ratio >= 0.25) return "danger";
  if (column.missing_ratio >= 0.05) return "warning";
  return "info";
}

export default function ModelReportPanel({
  tasks,
  selectedTask,
  report,
  reportState,
  reportError,
  onSelectTask,
  onRefreshReport,
  formatMetricName,
}) {
  const analysis = selectedTask?.structured_requirements && typeof selectedTask.structured_requirements === "object"
    ? selectedTask.structured_requirements
    : null;
  const datasetProfile = report?.dataset_profile ?? analysis?.dataset_profile ?? null;
  const featureImportance = Array.isArray(report?.feature_importance) ? report.feature_importance : [];
  const resultSummary = Array.isArray(report?.result_summary) ? report.result_summary : [];
  const qualityNotes = Array.isArray(report?.data_quality_notes) ? report.data_quality_notes : [];
  const limitationNotes = Array.isArray(report?.limitation_notes) ? report.limitation_notes : [];
  const metricName = formatMetricName ?? ((value) => value || "暂无");

  return (
    <div className="detail-stack">
      <section className="section-card">
        <div className="section-head">
          <div>
            <h3>选择任务</h3>
            <p>报告页读取后端生成的真实报告对象，包括数据质量、结果解释和产物缺口。</p>
          </div>
          <button type="button" className="chip-button" onClick={onRefreshReport} disabled={!selectedTask || reportState === "loading"}>
            {reportState === "loading" ? "生成中..." : "刷新报告"}
          </button>
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
                  <span>{task.last_run ? "已有结果" : "暂无结果"}</span>
                </div>
                <p>{task.dataset_filename || "未上传数据集"}</p>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {reportError ? <div className="error-banner">{reportError}</div> : null}
      {!selectedTask ? <div className="empty-state">先选择一个任务，再查看模型报告。</div> : null}

      {selectedTask ? (
        <>
          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>任务概览</h3>
                <p>报告页会把任务语义、AI 解析和 MLZero 成功结果放在一起看。</p>
              </div>
              {report?.generated_at ? <span className="runtime-pill info">报告时间 {formatDateTime(report.generated_at)}</span> : null}
            </div>

            <div className="summary-grid">
              <article className="summary-item"><span>任务名称</span><strong>{selectedTask.name}</strong></article>
              <article className="summary-item"><span>数据集</span><strong>{selectedTask.dataset_filename || "未上传"}</strong></article>
              <article className="summary-item"><span>目标列</span><strong>{selectedTask.label_column || "未解析"}</strong></article>
              <article className="summary-item"><span>任务类型</span><strong>{selectedTask.problem_type || "未解析"}</strong></article>
              <article className="summary-item"><span>建议指标</span><strong>{metricName(analysis?.metric_name || selectedTask.last_run?.metric_name)}</strong></article>
              <article className="summary-item"><span>AI 置信度</span><strong>{formatConfidence(analysis?.confidence)}</strong></article>
            </div>
          </section>

          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>数据质量摘要</h3>
                <p>这里来自上传 CSV 的真实画像，包括行列规模、字段类型和缺失值。</p>
              </div>
            </div>

            {datasetProfile ? (
              <div className="detail-stack">
                <div className="summary-grid">
                  <article className="summary-item"><span>行数</span><strong>{datasetProfile.row_count}</strong></article>
                  <article className="summary-item"><span>列数</span><strong>{datasetProfile.column_count}</strong></article>
                  <article className="summary-item"><span>目标列</span><strong>{datasetProfile.target_column || selectedTask.label_column || "未解析"}</strong></article>
                  <article className="summary-item"><span>预览行</span><strong>{Array.isArray(datasetProfile.preview_rows) ? datasetProfile.preview_rows.length : 0}</strong></article>
                </div>

                {qualityNotes.length ? (
                  <div className="callout">
                    <strong>质量结论</strong>
                    <ul className="compact-list">
                      {qualityNotes.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                ) : null}

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr><th>字段</th><th>类型</th><th>非空</th><th>缺失率</th><th>样例</th></tr>
                    </thead>
                    <tbody>
                      {(datasetProfile.columns ?? []).slice(0, 30).map((column) => (
                        <tr key={column.name}>
                          <td>{column.name}</td>
                          <td>{column.inferred_type}</td>
                          <td>{column.non_empty_count}</td>
                          <td><span className={`runtime-pill ${getMissingTone(column)}`}>{formatPercent(column.missing_ratio)}</span></td>
                          <td>{(column.sample_values ?? []).join(" / ") || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <div className="empty-state">当前还没有可读取的数据集画像。</div>
            )}
          </section>

          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>AI 解析结论</h3>
                <p>这里展示任务字段自动解析的理由和时间，不会伪造自然语言总结。</p>
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
                <h3>MLZero 结果与解释</h3>
                <p>这里只展示已经真实完成的最近一次成功结果。</p>
              </div>
            </div>

            {selectedTask.last_run ? (
              <div className="detail-stack">
                <div className="summary-grid">
                  <article className="summary-item"><span>最佳模型</span><strong>{selectedTask.last_run.best_model}</strong></article>
                  <article className="summary-item"><span>指标名称</span><strong>{metricName(selectedTask.last_run.metric_name)}</strong></article>
                  <article className="summary-item"><span>指标数值</span><strong>{formatMetricValue(selectedTask.last_run.metric_value)}</strong></article>
                  <article className="summary-item"><span>输出目录</span><strong className="mono-text">{selectedTask.last_run.output_dir}</strong></article>
                </div>
                {resultSummary.length ? (
                  <div className="callout">
                    <strong>结果解释</strong>
                    <ul className="compact-list">
                      {resultSummary.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="empty-state">当前还没有成功运行结果，因此暂时无法生成模型报告摘要。</div>
            )}
          </section>

          {selectedTask.last_run ? (
            <LeaderboardPanel
              run={selectedTask.last_run}
              formatMetricName={metricName}
              formatMetricValue={formatMetricValue}
            />
          ) : null}

          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>特征重要性</h3>
                <p>只有当真实运行产物中存在 feature importance 文件时才展示排名。</p>
              </div>
            </div>
            {featureImportance.length ? (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>特征</th><th>重要性</th><th>来源</th></tr></thead>
                  <tbody>
                    {featureImportance.map((item) => (
                      <tr key={`${item.feature}-${item.source ?? ""}`}>
                        <td>{item.feature}</td>
                        <td>{formatMetricValue(item.importance)}</td>
                        <td className="mono-text">{item.source || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-state compact">当前运行产物中没有可解析的特征重要性文件。</div>
            )}
          </section>

          <section className="section-card">
            <div className="section-head">
              <div>
                <h3>风险和局限</h3>
                <p>这里基于真实数据规模、候选模型和产物完整度生成。</p>
              </div>
            </div>
            {limitationNotes.length ? (
              <ul className="compact-list">
                {limitationNotes.map((item) => <li key={item}>{item}</li>)}
              </ul>
            ) : <div className="empty-state compact">暂无额外风险说明。</div>}
          </section>

          {report?.report_markdown ? (
            <section className="section-card">
              <div className="section-head">
                <div>
                  <h3>报告 Markdown</h3>
                  <p>这是后端基于真实记录生成的可导出文本。</p>
                </div>
              </div>
              <pre className="conversation-state-body">{report.report_markdown}</pre>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
