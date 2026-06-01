export function formatMetricValue(value) {
  if (typeof value === 'number') return Number.isInteger(value) ? value : value.toFixed(4)
  return value || '-'
}

export function formatPredictionValue(value) {
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value)
    return Number.isInteger(value) ? String(value) : value.toLocaleString(undefined, { maximumFractionDigits: 6 })
  }
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .map(([key, item]) => `${key}: ${formatPredictionValue(item)}`)
      .join('；')
  }
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

export function formatTokenCount(value) {
  const numeric = Number(value || 0)
  if (!Number.isFinite(numeric) || numeric <= 0) return '-'
  return new Intl.NumberFormat('zh-CN').format(Math.round(numeric))
}

export function formatDateTime(value, options = {}) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const fields = {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }
  if (options.includeSeconds) fields.second = '2-digit'
  return new Intl.DateTimeFormat('zh-CN', fields).format(date)
}

export function formatDateTimeWithSeconds(value) {
  return formatDateTime(value, { includeSeconds: true })
}

export function quotaRemaining(user) {
  return Math.max(0, Number(user?.token_quota || 0) - Number(user?.token_used || 0))
}

export function featureLabel(name) {
  return String(name || '').replace(/^num__/, '').replace(/^cat__/, '').replace(/__/g, '_').replace(/_/g, ' ')
}

export function checkLabel(name) {
  const map = {
    baseline_comparison: '简单对照',
    validation_split: '结果检查',
    leakage_check: '泄漏检查',
    artifact_consistency: '产物一致性',
    prediction_entrypoint: '预测入口',
    data_quality: '数据质量',
  }
  return map[name] || name || '检查项'
}
