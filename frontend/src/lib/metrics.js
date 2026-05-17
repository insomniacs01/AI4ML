const LOWER_IS_BETTER_METRICS = new Set([
  "rmse",
  "root_mean_squared_error",
  "mse",
  "mean_squared_error",
  "mae",
  "mean_absolute_error",
  "median_absolute_error",
  "log_loss",
  "pinball_loss",
]);

const METRIC_DEFINITIONS = {
  validation_score: {
    label: "候选排序分（内部）",
    direction: "越大越好",
    meaning: "同一次运行里给候选模型排名用的内部数值，不等同于业务效果指标。",
  },
  accuracy: {
    label: "准确率",
    direction: "越大越好",
    meaning: "分类任务中预测正确的样本比例。",
  },
  balanced_accuracy: {
    label: "平衡准确率",
    direction: "越大越好",
    meaning: "先分别计算各类别召回率，再取平均，适合类别不均衡的分类任务。",
  },
  f1: {
    label: "F1",
    direction: "越大越好",
    meaning: "精确率和召回率的综合指标，适合只看准确率不够的分类任务。",
  },
  precision: {
    label: "Precision",
    direction: "越大越好",
    meaning: "被模型判为正类的样本中，有多少是真的正类。",
  },
  recall: {
    label: "Recall",
    direction: "越大越好",
    meaning: "真实正类样本中，有多少被模型找出来。",
  },
  roc_auc: {
    label: "ROC AUC",
    direction: "越大越好",
    meaning: "衡量二分类模型区分正负样本的能力。",
  },
  auc: {
    label: "AUC",
    direction: "越大越好",
    meaning: "衡量分类模型区分不同类别的能力。",
  },
  r2: {
    label: "R²",
    direction: "越大越好",
    meaning: "回归模型对目标变量变化的解释程度。",
  },
  rmse: {
    label: "RMSE",
    direction: "越小越好",
    meaning: "回归预测误差的均方根，单位和目标列一致，对大误差更敏感。",
  },
  root_mean_squared_error: {
    label: "RMSE",
    direction: "越小越好",
    meaning: "回归预测误差的均方根，单位和目标列一致，对大误差更敏感。",
  },
  mse: {
    label: "MSE",
    direction: "越小越好",
    meaning: "回归预测误差平方的平均值，对大误差非常敏感。",
  },
  mean_squared_error: {
    label: "MSE",
    direction: "越小越好",
    meaning: "回归预测误差平方的平均值，对大误差非常敏感。",
  },
  mae: {
    label: "MAE",
    direction: "越小越好",
    meaning: "回归预测误差绝对值的平均值，单位和目标列一致。",
  },
  mean_absolute_error: {
    label: "MAE",
    direction: "越小越好",
    meaning: "回归预测误差绝对值的平均值，单位和目标列一致。",
  },
  log_loss: {
    label: "Log Loss",
    direction: "越小越好",
    meaning: "分类概率预测的损失，错误且自信的预测会被惩罚得更重。",
  },
};

export function normalizeMetricKey(name) {
  if (typeof name !== "string") return "";
  return name.trim().toLowerCase().replace(/[\s-]+/g, "_");
}

export function isLowerBetterMetric(name) {
  return LOWER_IS_BETTER_METRICS.has(normalizeMetricKey(name));
}

export function getMetricInfo(name) {
  const key = normalizeMetricKey(name);
  const known = METRIC_DEFINITIONS[key];
  if (known) return { key, ...known, known: true };
  if (!key) {
    return {
      key: "",
      label: "暂无",
      direction: "未记录",
      meaning: "这次运行没有记录明确的评估指标。",
      known: false,
    };
  }
  return {
    key,
    label: name,
    direction: isLowerBetterMetric(key) ? "越小越好" : "越大越好",
    meaning: "这是本次运行结果中记录的评估指标，具体业务含义需要结合任务目标确认。",
    known: false,
  };
}

export function formatMetricName(name) {
  return getMetricInfo(name).label;
}

export function getMetricDirectionLabel(name) {
  return getMetricInfo(name).direction;
}

export function getMetricMeaning(name) {
  return getMetricInfo(name).meaning;
}

export function getValidationScoreExplanation(metricName) {
  const info = getMetricInfo(metricName);
  if (!info.key || info.key === "validation_score") {
    return "候选排序分是内部排名用的数：同一次运行里越大越靠前。它只能说明这一批候选模型谁排第一，不能单独证明模型效果好。";
  }
  if (isLowerBetterMetric(info.key)) {
    return `${info.label} 本身是${info.direction}；系统会另外换算一个越大越好的候选排序分来排模型。判断效果时优先看 ${info.label} 的指标值，再和基线或业务阈值比较。`;
  }
  return `${info.label} 是这次验证集上的主要指标，通常${info.direction}。候选排序分只用于同一次运行内排序，判断好坏还要看目标列是否正确、验证方式是否可靠、是否超过基线。`;
}

export function getMetricQualityChecklist(metricName) {
  const info = getMetricInfo(metricName);
  return [
    "先确认目标列选对了，否则分数没有业务意义。",
    `看清指标：${info.label}，判断方向是${info.direction}。`,
    "再和简单基线、历史模型或业务阈值比较，不能只看一个孤立数字。",
  ];
}

export function getRunValidationScore(run) {
  if (typeof run?.validation_score === "number" && Number.isFinite(run.validation_score)) return run.validation_score;
  const rows = Array.isArray(run?.leaderboard) ? run.leaderboard : [];
  const bestModel = typeof run?.best_model === "string" ? run.best_model : "";
  const bestRow = rows.find((row) => row?.model === bestModel) ?? rows[0];
  const value = bestRow?.validation_score ?? bestRow?.score_val ?? bestRow?.score ?? null;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}
