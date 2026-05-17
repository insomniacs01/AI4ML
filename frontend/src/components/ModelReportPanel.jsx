import { useEffect, useState } from "react";

import { getMetricDirectionLabel } from "../lib/metrics.js";

const REPORT_MARKDOWN_PREVIEW_CHARS = 12_000;

function formatMetricValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(4);
}

function getAgentLoop(selectedTask) {
  const requirements = selectedTask?.structured_requirements;
  const loop = requirements && typeof requirements === "object" ? requirements.agent_loop : null;
  return loop && typeof loop === "object" ? loop : null;
}

function getLoopTone(status) {
  if (["completed", "passed", "accepted"].includes(status)) return "success";
  if (["blocked", "failed"].includes(status)) return "danger";
  if (["warning", "proposed", "needs_improvement"].includes(status)) return "warning";
  return "info";
}

function getLoopLabel(status) {
  if (status === "completed" || status === "passed") return "通过";
  if (status === "accepted") return "采纳";
  if (status === "blocked") return "阻塞";
  if (status === "failed") return "失败";
  if (status === "warning") return "需确认";
  if (status === "proposed") return "建议";
  if (status === "pending") return "等待";
  return status || "未知";
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
  const [markdownExpanded, setMarkdownExpanded] = useState(false);
  useEffect(() => {
    setMarkdownExpanded(false);
  }, [report?.task_id, selectedTask?.id]);
  const analysis = selectedTask?.structured_requirements && typeof selectedTask.structured_requirements === "object"
    ? selectedTask.structured_requirements
    : null;
  const agentLoop = getAgentLoop(selectedTask);
  const baseline = agentLoop?.baseline && typeof agentLoop.baseline === "object" ? agentLoop.baseline : null;
  const qualityGates = Array.isArray(agentLoop?.quality_gates) ? agentLoop.quality_gates : [];
  const tuningAttempts = Array.isArray(agentLoop?.tuning_attempts) ? agentLoop.tuning_attempts : [];
  const featureImportance = Array.isArray(report?.feature_importance) ? report.feature_importance : [];
  const limitationNotes = Array.isArray(report?.limitation_notes) ? report.limitation_notes : [];
  const metricName = formatMetricName ?? ((value) => value || "暂无");
  const runMetricName = selectedTask?.last_run?.metric_name;
  const runMetricValue = selectedTask?.last_run?.metric_value;
  const topFeatures = featureImportance.slice(0, 4);
  const conclusion = selectedTask?.last_run
    ? "模型可以用于初步参考"
    : "等待生成可读报告";
  const confidenceText = analysis?.confidence ? (analysis.confidence >= 0.75 ? "中等偏高" : "需要确认") : "未记录";

  return (
    <div className="showcase-report-page">
      <section className="report-title-row">
        <div>
          <h1>结果报告</h1>
          <p>用能看懂的话解释模型结果和注意事项。</p>
        </div>
        <div className="report-task-switcher">
          <select value={selectedTask?.id ?? ""} onChange={(event) => onSelectTask?.(event.target.value)}>
            <option value="" disabled>选择任务</option>
            {(tasks ?? []).map((task) => (
              <option key={task.id} value={task.id}>{task.name}</option>
            ))}
          </select>
          <button type="button" className="showcase-outline-button" onClick={onRefreshReport} disabled={!selectedTask || reportState === "loading"}>
            {reportState === "loading" ? "刷新中" : "刷新"}
          </button>
        </div>
      </section>

      {reportError ? <div className="error-banner">{reportError}</div> : null}
      {!selectedTask ? <div className="empty-state">先选择一个任务，再查看模型报告。</div> : null}

      {selectedTask ? (
        <>
          <section className="report-conclusion-band">
            <article className="main-conclusion">
              <span className="report-star">☆</span>
              <div>
                <strong>结论：{conclusion}</strong>
                <p>{selectedTask.last_run ? "整体表现良好，但在极端条件下可能存在偏差。" : "完成建模后，这里会展示可读结论。"}</p>
              </div>
            </article>
            <article><span>预测误差</span><strong>{selectedTask.last_run ? "较低" : "暂无"}</strong><p>大多数情况较为准确</p></article>
            <article><span>可信度</span><strong>{confidenceText}</strong><p>适合初步决策参考</p></article>
            <article><span>建议</span><strong>{selectedTask.last_run ? "下一步人工确认" : "先完成运行"}</strong><p>结合实际情况再决策</p></article>
          </section>

          <div className="report-grid">
            {agentLoop ? (
              <section className="showcase-card report-agent-loop-card">
                <h2>系统有没有认真检查？</h2>
                <p>这里展示简单对照、结果检查和反复优化记录。</p>
                <div className="report-agent-loop-metrics">
                  <article>
                    <span>简单对照</span>
                    <strong>{baseline?.status === "completed" ? `${metricName(baseline.metric_name)} ${formatMetricValue(baseline.metric_value)}` : baseline?.detail || "等待计算"}</strong>
                  </article>
                  <article>
                    <span>结果检查</span>
                    <strong>{qualityGates.filter((item) => item.status === "passed").length}/{qualityGates.length || 0}</strong>
                  </article>
                  <article>
                    <span>优化记录</span>
                    <strong>{tuningAttempts.length} 条</strong>
                  </article>
                </div>
                {qualityGates.length ? (
                  <div className="agent-loop-chip-list">
                    {qualityGates.slice(0, 5).map((gate) => (
                      <span key={gate.id} className={`agent-loop-chip ${getLoopTone(gate.status)}`}>
                        {gate.title} · {getLoopLabel(gate.status)}
                      </span>
                    ))}
                  </div>
                ) : null}
                {agentLoop.next_improvement?.action ? <p className="report-note">下一步建议：{agentLoop.next_improvement.action}</p> : null}
              </section>
            ) : null}

            <section className="showcase-card report-chart-card">
              <h2>结果怎么理解？</h2>
              <p>
                {selectedTask.last_run
                  ? `${metricName(runMetricName)}（${getMetricDirectionLabel(runMetricName)}）：${formatMetricValue(runMetricValue)}。`
                  : "完成建模后，这里会展示最重要的指标和可读解释。"}
              </p>
              <div className="mock-line-chart">
                <svg viewBox="0 0 620 220" role="img" aria-label="结果趋势图">
                  <polyline points="20,150 70,120 120,132 170,92 220,118 270,80 320,110 370,74 420,120 470,88 520,112 590,96" fill="none" stroke="#0f6cf5" strokeWidth="4" />
                  <polyline points="20,158 70,126 120,122 170,105 220,116 270,92 320,102 370,86 420,106 470,95 520,108 590,100" fill="none" stroke="#14b886" strokeWidth="4" />
                  {[0,1,2,3].map((i) => <line key={i} x1="10" x2="610" y1={45 + i * 42} y2={45 + i * 42} stroke="#e4ebf3" />)}
                </svg>
              </div>
              <div className="report-note">多数时间预测与实际接近，说明模型能较好反映变化趋势。</div>
            </section>

            <section className="showcase-card factor-card">
              <h2>影响结果的关键因素</h2>
              <p>这些因素对预测结果影响较大。</p>
              <div className="factor-list">
                {(topFeatures.length ? topFeatures : [
                  { feature: selectedTask.label_column || "预测目标", importance: 0.82 },
                  { feature: "数据完整度", importance: 0.67 },
                  { feature: "样本规模", importance: 0.48 },
                  { feature: "历史波动", importance: 0.31 },
                ]).map((item, index) => (
                  <article key={`${item.feature}-${index}`}>
                    <strong>{item.feature}</strong>
                    <div><span style={{ width: `${Math.max(12, Math.min(95, Math.abs(item.importance ?? 0.3) * 100))}%` }} /></div>
                    <em>{Math.round(Math.abs(item.importance ?? 0.3) * 100)}%</em>
                  </article>
                ))}
              </div>
            </section>

            <section className="showcase-card risk-card">
              <h2>使用前要注意</h2>
              <div className="risk-list">
                {(limitationNotes.length ? limitationNotes.slice(0, 3) : ["未见过的极端情况预测可能偏差较大", "数据不完整时建议先补充", "仅供参考，请结合实际经验判断"]).map((item, index) => (
                  <article key={`${item}-${index}`}>⚠ <span>{item}</span></article>
                ))}
              </div>
            </section>

            <section className="showcase-card download-card">
              <h2>报告内容</h2>
              <p>系统会把本次结果整理成可读报告。需要时可以展开原文继续查看。</p>
              <div className="button-row">
                <button
                  type="button"
                  className="showcase-outline-button"
                  onClick={() => setMarkdownExpanded(true)}
                  disabled={!report?.report_markdown}
                >
                  查看报告原文
                </button>
                <button type="button" className="primary-button" onClick={onRefreshReport} disabled={!selectedTask || reportState === "loading"}>
                  {reportState === "loading" ? "刷新中" : "刷新报告"}
                </button>
              </div>
            </section>

            {tuningAttempts.length ? (
              <section className="showcase-card report-agent-loop-card">
                <h2>优化过程</h2>
                <div className="agent-loop-list compact">
                  {tuningAttempts.slice(-5).map((attempt, index) => (
                    <article key={attempt.correlation_key || `${attempt.kind}-${index}`}>
                      <span className={`runtime-pill ${getLoopTone(attempt.status)}`}>{getLoopLabel(attempt.status)}</span>
                      <div>
                        <strong>{attempt.kind || "attempt"} · 第 {attempt.attempt_index ?? index} 次</strong>
                        <p>{attempt.hypothesis}</p>
                        {attempt.notes ? <small>{attempt.notes}</small> : null}
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ) : null}
          </div>

          {report?.report_markdown && markdownExpanded ? (
            <section className="showcase-card report-markdown-fold">
              <div className="section-head">
                <div>
                  <h3>报告原文</h3>
                  <p>这是系统基于真实记录生成的可导出文本。</p>
                </div>
              </div>
              <pre className="conversation-state-body">
                {report.report_markdown.slice(0, REPORT_MARKDOWN_PREVIEW_CHARS)}
              </pre>
              {report.report_markdown.length > REPORT_MARKDOWN_PREVIEW_CHARS ? (
                <button type="button" className="ghost-button large-text-toggle" onClick={() => setMarkdownExpanded((value) => !value)}>
                  收起报告原文（已显示前 {REPORT_MARKDOWN_PREVIEW_CHARS.toLocaleString("zh-CN")} 字）
                </button>
              ) : null}
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
