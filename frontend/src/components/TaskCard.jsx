import { getBestLeaderboardEntry, getLeaderboardCandidateCount } from "../lib/leaderboard.js";

const STATUS_LABELS = {
  draft: "草稿",
  uploaded: "已上传数据集",
  planning: "规划中",
  paused_for_review: "等待复核",
  waiting_human: "等待人工协同",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  published: "已发布",
};

const PROBLEM_TYPE_LABELS = {
  classification: "分类",
  regression: "回归",
};

const METRIC_LABELS = {
  validation_score: "验证分数",
  accuracy: "准确率",
  rmse: "RMSE",
  mae: "MAE",
  roc_auc: "ROC AUC",
  auc: "AUC",
  f1: "F1",
};

function formatMetricValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(4);
}

function formatStatus(status) {
  return STATUS_LABELS[status] ?? status;
}

function formatProblemType(problemType) {
  if (!problemType) return "未解析";
  return PROBLEM_TYPE_LABELS[problemType] ?? problemType;
}

function formatMetricName(name) {
  if (!name) return "暂无";
  return METRIC_LABELS[name] ?? name;
}

function combineTotalTokens(task) {
  const analysisTotal = typeof task.analysis_token_usage?.total_tokens === "number" ? task.analysis_token_usage.total_tokens : null;
  const runTotal = typeof task.last_run_attempt?.token_usage?.total_tokens === "number"
    ? task.last_run_attempt.token_usage.total_tokens
    : typeof task.last_run?.token_usage?.total_tokens === "number"
      ? task.last_run.token_usage.total_tokens
      : null;
  if (analysisTotal === null && runTotal === null) return null;
  return Math.max(0, (analysisTotal ?? 0) + (runTotal ?? 0));
}

function getMetricSummary(task) {
  if (task.status === "failed" && task.last_run_attempt) {
    if (task.last_run) {
      return `本次运行失败，上一次成功结果 ${formatMetricName(task.last_run.metric_name)}：${formatMetricValue(task.last_run.metric_value)}`;
    }
    return "本次运行失败，尚未产出成功结果。";
  }
  if (!task.last_run) {
    return "还没有运行结果。";
  }
  const candidateCount = getLeaderboardCandidateCount(task.last_run.leaderboard, task.last_run.metric_name ?? "validation_score");
  const suffix = candidateCount > 1 ? `，共 ${candidateCount} 个候选` : "";
  return `${formatMetricName(task.last_run.metric_name)}：${formatMetricValue(task.last_run.metric_value)}${suffix}`;
}

function getAnalysisStatus(task) {
  if (task.label_column && task.problem_type) return "AI 已解析";
  if (task.dataset_filename) return "待 AI 解析";
  return "未上传数据";
}

function getTokenSummary(task) {
  const total = combineTotalTokens(task);
  if (total === null) return "未记录";
  return `${total.toLocaleString("zh-CN")} Token`;
}

function getBestCandidateSummary(task) {
  if (!task.last_run) return "暂无";
  const bestEntry = getBestLeaderboardEntry(task.last_run.leaderboard, task.last_run.metric_name ?? "validation_score");
  return bestEntry?.label ?? task.last_run.best_model ?? "暂无";
}

function getCandidateCountSummary(task) {
  if (!task.last_run) return "暂无";
  const candidateCount = getLeaderboardCandidateCount(task.last_run.leaderboard, task.last_run.metric_name ?? "validation_score");
  return candidateCount ? `${candidateCount} 个` : "未记录";
}

function getStatusTone(status) {
  if (status === "failed") return "danger";
  if (status === "completed" || status === "published") return "success";
  if (status === "waiting_human" || status === "paused_for_review") return "warning";
  return "info";
}

export default function TaskCard({
  task,
  selected,
  running,
  analyzing,
  deleting,
  onSelect,
  onAnalyze,
  onRun,
  onDelete,
  onOpenHumanCollaboration,
}) {
  return (
    <article className={selected ? "task-card selected-card" : "task-card"}>
      <div className="task-card-top">
        <div>
          <p className="eyebrow">任务 {task.id}</p>
          <h4>{task.name}</h4>
        </div>
        <span className={`runtime-pill ${getStatusTone(task.status)}`}>
          {formatStatus(task.status)}
        </span>
      </div>

      <p className="task-description">{task.description}</p>

      <dl className="task-meta">
        <div><dt>AI 解析</dt><dd>{getAnalysisStatus(task)}</dd></div>
        <div><dt>目标列</dt><dd>{task.label_column ?? "未解析"}</dd></div>
        <div><dt>任务类型</dt><dd>{formatProblemType(task.problem_type)}</dd></div>
        <div><dt>数据集</dt><dd>{task.dataset_filename ?? "未上传"}</dd></div>
        <div><dt>最新结果</dt><dd>{getMetricSummary(task)}</dd></div>
        <div><dt>最佳候选</dt><dd>{getBestCandidateSummary(task)}</dd></div>
        <div><dt>候选数</dt><dd>{getCandidateCountSummary(task)}</dd></div>
        <div><dt>Token</dt><dd>{getTokenSummary(task)}</dd></div>
        <div><dt>更新时间</dt><dd>{new Date(task.updated_at).toLocaleString()}</dd></div>
      </dl>

      {task.notes ? <p className="meta-note">{task.notes}</p> : null}

      <div className="button-row connector-actions">
        <button type="button" className="chip-button" onClick={() => onSelect(task.id)}>
          {selected ? "当前选中" : "查看详情"}
        </button>
        <button type="button" className="ghost-button" onClick={() => onAnalyze(task.id)} disabled={!task.dataset_filename || analyzing || running}>
          {analyzing ? "解析中..." : "AI 解析"}
        </button>
        <button type="button" className="primary-button" onClick={() => onRun(task.id)} disabled={!task.dataset_filename || running || ["waiting_human", "paused_for_review"].includes(task.status)}>
          {running ? "运行中..." : "运行"}
        </button>
        <button type="button" className="chip-button" onClick={() => onOpenHumanCollaboration?.(task.id)}>
          协同
        </button>
        <button type="button" className="danger-button" onClick={() => onDelete(task.id)} disabled={deleting || task.status === "running"}>
          {deleting ? "删除中..." : "删除"}
        </button>
      </div>
    </article>
  );
}
