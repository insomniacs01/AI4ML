import { compactDisplayText, looksLikeRawRuntimeText } from "./errorMessages.js";

export const PROBLEM_TYPE_LABELS = {
  classification: "分类",
  regression: "回归",
};

export const TASK_STATUS_LABELS = {
  draft: "草稿",
  uploaded: "已上传数据集",
  planning: "规划中",
  paused_for_review: "等待复核",
  waiting_human: "等待人工确认",
  running: "运行中",
  blocked: "自动处理受阻",
  repairing: "自动修复中",
  stale: "疑似卡住",
  completed: "已完成",
  failed: "失败",
  published: "已发布",
};

export const TASK_STATUS_TONES = {
  draft: "warning",
  uploaded: "info",
  planning: "info",
  paused_for_review: "warning",
  waiting_human: "warning",
  running: "info",
  blocked: "warning",
  repairing: "info",
  stale: "danger",
  completed: "success",
  failed: "danger",
  published: "success",
};

export const RUN_STATUS_LABELS = {
  not_started: "未开始",
  running: "运行中",
  repairing: "自动修复中",
  blocked: "自动处理受阻",
  stale: "疑似卡住",
  completed: "已完成",
  failed: "失败",
  unknown: "状态不完整",
};

export const WORKFLOW_STAGE_LABELS = {
  requirement_analysis: "需求解析",
  data_analysis: "数据分析",
  feature_engineering: "特征工程",
  model_selection: "模型选择",
  training_validation: "训练验证",
  report_generation: "报告生成",
};

export const DEFAULT_RUNTIME_TEXT_FALLBACK = "系统已隐藏原始运行日志；请查看诊断结论或报错文件。";

export function formatDateTime(value, fallback = "暂无") {
  if (!value) return fallback;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

export function formatProblemType(problemType, fallback = "未解析") {
  if (!problemType) return fallback;
  return PROBLEM_TYPE_LABELS[problemType] ?? problemType;
}

export function formatTaskStatus(status, fallback = "未知状态") {
  return TASK_STATUS_LABELS[status] ?? status ?? fallback;
}

export function getTaskStatusTone(status) {
  return TASK_STATUS_TONES[status] ?? "warning";
}

export function formatProgressStatus(status, fallback = "未知") {
  return RUN_STATUS_LABELS[status] ?? status ?? fallback;
}

export function formatWorkflowStage(stage, fallback = "未知阶段") {
  return WORKFLOW_STAGE_LABELS[stage] ?? stage ?? fallback;
}

export function isRecoverableRunBlockedTask(task) {
  const notes = String(task?.notes ?? "").toLowerCase();
  if (!notes) return false;
  if (notes.includes("agent") && notes.includes("修复受阻")) return true;
  if (!["running", "failed"].includes(task?.status)) return false;
  return [
    "apitimeouterror",
    "request timed out",
    "readtimeout",
    "retryerror",
    "modulenotfounderror",
    "no module named",
    "run_summary.json",
    "leaderboard",
  ].some((marker) => notes.includes(marker));
}

export function getTaskRuntimeStatus(task, runtimeProgress, running = false) {
  const progressStatus = runtimeProgress?.status;
  if (progressStatus === "blocked") return "blocked";
  if (progressStatus === "repairing") return "repairing";
  if (progressStatus === "stale") return "stale";
  if (progressStatus === "completed") return "completed";
  if (progressStatus === "failed") return "failed";
  if (progressStatus === "running") return "running";
  if (isRecoverableRunBlockedTask(task)) return "blocked";
  if (running || task?.status === "running") return "running";
  if (progressStatus === "unknown" || progressStatus === "not_started") return task?.status ?? "draft";
  return task?.status ?? "draft";
}

export function isRawRuntimeDebugText(value) {
  return looksLikeRawRuntimeText(value);
}

export function sanitizeRuntimeText(value, fallback = DEFAULT_RUNTIME_TEXT_FALLBACK) {
  if (!value) return "";
  const text = String(value).replace(/\s+/g, " ").trim();
  if (!text) return "";
  return looksLikeRawRuntimeText(text) ? fallback : text;
}

export function compactStatusLabel(value, maxLength = 14) {
  return compactDisplayText(value, maxLength);
}

export function getReadableRuntimeActivity(runtimeProgress) {
  const activity = runtimeProgress?.observer_status
    ? `${runtimeProgress.observer_status}${runtimeProgress.observer_detail ? `：${runtimeProgress.observer_detail}` : ""}`
    : runtimeProgress?.current_activity;
  if (!activity || looksLikeRawRuntimeText(activity)) return "";
  return sanitizeRuntimeText(activity);
}

export function formatRuntimeStatusLabel(runtimeStatus, runProgress, maxLength = 18) {
  if (runtimeStatus === "blocked") {
    const readable = getReadableRuntimeActivity(runProgress);
    return readable ? compactStatusLabel(readable, maxLength) : "自动处理受阻";
  }
  if (runtimeStatus === "repairing") return "自动修复中";
  if (runtimeStatus === "stale") return "疑似卡住";
  const readable = getReadableRuntimeActivity(runProgress);
  if (runProgress?.status === "running") {
    if (readable) return compactStatusLabel(readable, maxLength);
    if (runProgress.current_model) return compactStatusLabel(`训练 ${runProgress.current_model}`, maxLength);
    if (runProgress.current_stage) return formatWorkflowStage(runProgress.current_stage);
  }
  if (runProgress?.status === "completed" && runProgress?.artifacts?.best_model) {
    return compactStatusLabel(`最佳 ${runProgress.artifacts.best_model}`, maxLength);
  }
  if (readable) return compactStatusLabel(readable, maxLength);
  return formatTaskStatus(runtimeStatus);
}

export function formatTaskAnalysisStatus(task) {
  if (task?.label_column && task?.problem_type) return "AI 已解析";
  if (task?.dataset_filename) return "待 AI 解析";
  return "未上传数据";
}
