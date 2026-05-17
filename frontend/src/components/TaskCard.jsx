import { getLeaderboardCandidateCount } from "../lib/leaderboard.js";
import { formatMetricName, getMetricDirectionLabel } from "../lib/metrics.js";
import {
  compactStatusLabel,
  formatProblemType,
  formatRuntimeStatusLabel,
  formatTaskAnalysisStatus,
  getReadableRuntimeActivity,
  getTaskRuntimeStatus,
  isRecoverableRunBlockedTask,
  sanitizeRuntimeText,
} from "../lib/taskPresentation.js";

function formatMetricValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(4);
}

function getMetricSummary(task) {
  if (isRecoverableRunBlockedTask(task)) {
    if (task.last_run) {
      return `自动处理受阻，上一次成功结果 ${formatMetricName(task.last_run.metric_name)}：${formatMetricValue(task.last_run.metric_value)}`;
    }
    return "自动处理受阻，已保留本次生成文件。";
  }
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
  return `${formatMetricName(task.last_run.metric_name)}（${getMetricDirectionLabel(task.last_run.metric_name)}）：${formatMetricValue(task.last_run.metric_value)}${suffix}`;
}

function getStatusTone(status) {
  if (status === "blocked") return "warning";
  if (status === "repairing") return "info";
  if (status === "failed") return "danger";
  if (status === "completed" || status === "published") return "success";
  if (status === "waiting_human" || status === "paused_for_review") return "warning";
  return "info";
}

function getAgentLoop(task) {
  const requirements = task?.structured_requirements;
  const loop = requirements && typeof requirements === "object" ? requirements.agent_loop : null;
  return loop && typeof loop === "object" ? loop : null;
}

function formatLoopMetric(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "暂无";
  return Math.abs(value) >= 1 ? value.toFixed(4) : value.toPrecision(4);
}

function getLoopStatus(task) {
  const loop = getAgentLoop(task);
  if (!loop) return null;
  const baseline = loop.baseline && typeof loop.baseline === "object" ? loop.baseline : null;
  const gates = Array.isArray(loop.quality_gates) ? loop.quality_gates : [];
  const attempts = Array.isArray(loop.tuning_attempts) ? loop.tuning_attempts : [];
  const blocked = gates.filter((item) => item.status === "blocked").length;
  const warnings = gates.filter((item) => item.status === "warning").length;
  const baselineText = baseline?.status === "completed"
    ? `${formatMetricName(baseline.metric_name)} ${formatLoopMetric(baseline.metric_value)}`
    : baseline?.detail || "等待简单对照";
  return { baselineText, blocked, warnings, attempts: attempts.length };
}

export default function TaskCard({
  task,
  selected,
  running,
  analyzing,
  deleting,
  runtimeProgress,
  onSelect,
  onAnalyze,
  onRun,
  onDelete,
  onOpenWorkflow,
  onOpenHumanCollaboration,
}) {
  const runtimeStatus = getTaskRuntimeStatus(task, runtimeProgress, running);
  const isRunning = running || ["running", "repairing"].includes(runtimeStatus);
  const statusTone = runtimeStatus === "stale" ? "danger" : getStatusTone(runtimeStatus);
  const statusLabel = formatRuntimeStatusLabel(runtimeStatus, runtimeProgress, 14);
  const safeNotes = sanitizeRuntimeText(task.notes, "");
  const statusHint = getReadableRuntimeActivity(runtimeProgress) || safeNotes || "";
  const loopStatus = getLoopStatus(task);
  return (
    <article className={selected ? "task-card selected-card" : "task-card"}>
      <div className="task-card-top">
        <div>
          <p className="eyebrow">建模任务</p>
          <h4>{task.name}</h4>
        </div>
        <span className={`runtime-pill ${statusTone}`}>
          {statusLabel}
        </span>
      </div>

      <p className="task-description">{task.description}</p>

      <div className="task-card-statusline">
        <span>AI 理解：{formatTaskAnalysisStatus(task)}</span>
        <span>数据：{task.dataset_filename ?? "未上传"}</span>
      </div>
      {statusHint ? <p className="task-card-runtime-hint">{compactStatusLabel(statusHint, 120)}</p> : null}
      {loopStatus ? (
        <div className="task-card-loopline">
          <span>简单对照：{loopStatus.baselineText}</span>
          <span>优化：{loopStatus.attempts} 条</span>
          <span>检查：{loopStatus.blocked ? `${loopStatus.blocked} 个问题` : loopStatus.warnings ? `${loopStatus.warnings} 个提醒` : "通过"}</span>
        </div>
      ) : null}

      <div className="task-card-facts">
        <div><span>目标</span><strong>{task.label_column ?? "等待 AI 判断"}</strong></div>
        <div><span>问题</span><strong>{formatProblemType(task.problem_type)}</strong></div>
        <div><span>结果</span><strong>{getMetricSummary(task)}</strong></div>
      </div>

      <div className="task-card-foot">
        <span>更新时间</span>
        <time>{new Date(task.updated_at).toLocaleString()}</time>
      </div>

      {safeNotes ? <p className="meta-note">{safeNotes}</p> : null}

      <div className="button-row connector-actions task-card-actions">
        <button type="button" className="chip-button" onClick={() => onSelect(task.id)}>
          {selected ? "已打开" : "打开"}
        </button>
        <button type="button" className="ghost-button" onClick={() => onAnalyze(task.id)} disabled={!task.dataset_filename || analyzing || isRunning}>
          {analyzing ? "理解中..." : "AI 理解"}
        </button>
        <button type="button" className="primary-button" onClick={() => onRun(task.id)} disabled={!task.dataset_filename || isRunning || ["waiting_human", "paused_for_review"].includes(task.status)}>
          {isRunning ? "建模中..." : "开始建模"}
        </button>
        <button type="button" className="chip-button" onClick={() => onOpenWorkflow?.(task.id)}>
          看进度
        </button>
        <button type="button" className="chip-button" onClick={() => onOpenHumanCollaboration?.(task.id)}>
          复核
        </button>
        <button type="button" className="danger-button" onClick={() => onDelete(task.id)} disabled={deleting || isRunning}>
          {deleting ? "删除中..." : "删除"}
        </button>
      </div>
    </article>
  );
}
