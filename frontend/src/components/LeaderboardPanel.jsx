import { formatDurationSeconds, normalizeLeaderboardEntries } from "../lib/leaderboard.js";
import {
  formatMetricName as formatCatalogMetricName,
  getMetricDirectionLabel,
  getMetricQualityChecklist,
  getRunValidationScore,
  getValidationScoreExplanation,
} from "../lib/metrics.js";

function defaultFormatMetricValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(4);
}

function defaultFormatMetricName(name) {
  return formatCatalogMetricName(name);
}

export default function LeaderboardPanel({
  run,
  formatMetricName = defaultFormatMetricName,
  formatMetricValue = defaultFormatMetricValue,
  embedded = false,
}) {
  if (!run) return null;
  const entries = normalizeLeaderboardEntries(run.leaderboard ?? [], run.metric_name ?? "validation_score");
  const metricName = run.metric_name ?? entries[0]?.metricName ?? "validation_score";
  const searchScore = getRunValidationScore(run);
  const checklist = getMetricQualityChecklist(metricName);

  return (
    <section className={embedded ? "leaderboard-panel-embedded" : "section-card"}>
      <div className="section-head">
        <div>
          <h3>候选模型对比</h3>
          <p>这里展示的是本次成功运行真实保存下来的候选模型对比，不是前端推断出来的假数据。</p>
        </div>
      </div>

      {!entries.length ? (
        <div className="empty-state">
          这次成功运行还没有产出可读取的候选模型对比文件。新的运行已经会优先读取
          {" "}
          <code>leaderboard.json</code>
          {" "}
          或
          {" "}
          <code>leaderboard.csv</code>
          {" "}
          并直接展示在这里。
        </div>
      ) : (
        <div className="detail-stack">
          <div className="callout leaderboard-callout">
            <strong>这个分数到底是什么</strong>
            <p>{getValidationScoreExplanation(metricName)}</p>
            <ul className="compact-list">
              {checklist.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </div>

          <div className="summary-grid">
            <article className="summary-item"><span>主要指标</span><strong>{formatMetricName(metricName)}</strong></article>
            <article className="summary-item"><span>判断方向</span><strong>{getMetricDirectionLabel(metricName)}</strong></article>
            <article className="summary-item"><span>指标数值</span><strong>{formatMetricValue(run.metric_value)}</strong></article>
            <article className="summary-item"><span>候选排序分（内部）</span><strong>{formatMetricValue(searchScore)}</strong></article>
          </div>

          <div className="table-wrap">
            <table className="leaderboard-table">
              <thead>
                <tr>
                  <th>排名</th>
                  <th>候选模型</th>
                  <th>来源</th>
                  <th>指标</th>
                  <th>指标值 / 候选排序分</th>
                  <th>耗时</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={`${entry.rank}-${entry.label}`}>
                    <td><span className="leaderboard-rank">#{entry.rank}</span></td>
                    <td className="leaderboard-model-cell">
                      <div className="table-cell-stack">
                        <strong>{entry.label}</strong>
                        {entry.node && entry.node !== entry.label ? <span>{entry.node}</span> : null}
                      </div>
                    </td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{entry.tool || "未记录"}</strong>
                        {entry.tool && entry.node ? <span>{entry.node}</span> : null}
                      </div>
                    </td>
                    <td>{formatMetricName(entry.metricName)}</td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>{formatMetricValue(entry.metricValue ?? entry.validationScore)}</strong>
                        {typeof entry.metricValue === "number" && typeof entry.validationScore === "number" && Math.abs(entry.metricValue - entry.validationScore) > 1e-12 ? (
                          <span>候选排序分 {formatMetricValue(entry.validationScore)}</span>
                        ) : <span>候选排序分只用于同次运行内排名，越大越靠前</span>}
                      </div>
                    </td>
                    <td>
                      <div className="table-cell-stack">
                        <strong>训练 {formatDurationSeconds(entry.fitTime)}</strong>
                        <span>预测 {formatDurationSeconds(entry.predTime)}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
