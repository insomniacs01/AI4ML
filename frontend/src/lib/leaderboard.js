const SCORE_KEYS = ["validation_score", "score_val", "score", "search_score", "best_score", "metric_value"];
const METRIC_VALUE_KEYS = ["metric_value", "display_metric_value", "raw_metric_value"];
const MODEL_KEYS = ["model", "best_model", "candidate_model", "model_name", "name"];
const METRIC_KEYS = ["metric_name", "display_metric_name", "raw_metric_name", "eval_metric", "metric"];
const NODE_KEYS = ["node", "best_node"];
const TOOL_KEYS = ["tool", "library", "framework"];
const FIT_TIME_KEYS = ["fit_time", "fit_time_marginal", "fit_seconds", "train_time", "training_time"];
const PRED_TIME_KEYS = ["pred_time", "pred_time_val", "pred_time_test", "pred_seconds", "predict_time"];

function pickString(entry, keys) {
  for (const key of keys) {
    const value = entry?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function pickNumber(entry, keys) {
  for (const key of keys) {
    const value = entry?.[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}

function pickRank(entry, index) {
  const rank = pickNumber(entry, ["rank"]);
  return Number.isInteger(rank) && rank > 0 ? rank : index + 1;
}

function normalizeEntry(entry, index, fallbackMetricName) {
  if (!entry || typeof entry !== "object") return null;
  const validationScore = pickNumber(entry, SCORE_KEYS);
  const label = pickString(entry, MODEL_KEYS) || pickString(entry, NODE_KEYS);
  if (validationScore === null && !label) return null;

  const metricValue = pickNumber(entry, METRIC_VALUE_KEYS);
  return {
    rank: pickRank(entry, index),
    label: label || `候选 ${index + 1}`,
    node: pickString(entry, NODE_KEYS),
    tool: pickString(entry, TOOL_KEYS),
    metricName: pickString(entry, METRIC_KEYS) || fallbackMetricName,
    validationScore,
    metricValue,
    fitTime: pickNumber(entry, FIT_TIME_KEYS),
    predTime: pickNumber(entry, PRED_TIME_KEYS),
  };
}

export function normalizeLeaderboardEntries(entries, fallbackMetricName = "validation_score") {
  const normalized = Array.isArray(entries)
    ? entries.map((entry, index) => normalizeEntry(entry, index, fallbackMetricName)).filter(Boolean)
    : [];
  const hasExplicitRank = normalized.some((entry, index) => entry.rank !== index + 1);
  return [...normalized].sort((left, right) => {
    if (hasExplicitRank) return left.rank - right.rank;
    const leftScore = typeof left.validationScore === "number" ? left.validationScore : Number.NEGATIVE_INFINITY;
    const rightScore = typeof right.validationScore === "number" ? right.validationScore : Number.NEGATIVE_INFINITY;
    return rightScore - leftScore;
  });
}

export function getBestLeaderboardEntry(entries, fallbackMetricName = "validation_score") {
  return normalizeLeaderboardEntries(entries, fallbackMetricName)[0] ?? null;
}

export function getLeaderboardCandidateCount(entries, fallbackMetricName = "validation_score") {
  return normalizeLeaderboardEntries(entries, fallbackMetricName).length;
}

export function formatDurationSeconds(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "未记录";
  if (value < 1) return `${value.toFixed(2)}s`;
  if (value < 60) return `${value.toFixed(1)}s`;
  return `${(value / 60).toFixed(1)}m`;
}
