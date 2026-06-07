import { formatTokenCount } from './formatters'

export function predictionValueFromPayload(payload, { targetName = '', requiredFeatures = [] } = {}) {
  if (payload === null || payload === undefined) return null
  if (typeof payload !== 'object') return { value: payload }

  const prediction = payload.prediction
  if (prediction && typeof prediction === 'object') {
    const outputMap = prediction.predictions || prediction.outputs || prediction.target_predictions
    if (outputMap && typeof outputMap === 'object' && !Array.isArray(outputMap)) {
      return { label: '多目标预测', value: outputMap }
    }
    if (Object.prototype.hasOwnProperty.call(prediction, 'label')) return { value: prediction.label }
    if (Object.prototype.hasOwnProperty.call(prediction, 'value')) return { value: prediction.value }
    if (Object.prototype.hasOwnProperty.call(prediction, 'prediction')) return { value: prediction.prediction }
    if (prediction.result && typeof prediction.result === 'object') {
      const result = prediction.result
      const targetMap = result.predictions || result.outputs || result.target_predictions
      if (targetMap && typeof targetMap === 'object' && !Array.isArray(targetMap)) {
        return { label: '多目标预测', value: targetMap }
      }
      const knownKeys = ['predicted_value', 'prediction', 'predicted', 'label', targetName]
      const key = knownKeys.find((item) => item && Object.prototype.hasOwnProperty.call(result, item))
      if (key) return { value: result[key] }
      const candidate = Object.entries(result).find(([name]) => !requiredFeatures.includes(name))
      if (candidate) return { label: candidate[0], value: candidate[1] }
    }
  }

  const directKeys = ['predicted_value', 'prediction', 'predicted', 'label', 'value']
  const directKey = directKeys.find((key) => Object.prototype.hasOwnProperty.call(payload, key))
  if (directKey) return { value: payload[directKey] }
  const outputMap = payload.predictions || payload.outputs || payload.target_predictions
  if (outputMap && typeof outputMap === 'object' && !Array.isArray(outputMap)) {
    return { label: '多目标预测', value: outputMap }
  }
  return null
}

function normalizedChartRows(rows, fields) {
  if (!Array.isArray(rows) || rows.length < 2) return []
  return rows.map((item) => {
    const values = {}
    for (const field of fields) {
      const value = Number(item[field])
      if (!Number.isFinite(value)) return null
      values[field] = value
    }
    return values
  }).filter(Boolean)
}

function polylineFromValues(rows, field, min, span) {
  return rows.map((item, index) => {
    const x = rows.length === 1 ? 0 : (index / (rows.length - 1)) * 100
    const y = 76 - ((item[field] - min) / span) * 58
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

export function comparisonChartPolylinePoints(rows, fields = ['actual', 'predicted']) {
  const sampleRows = normalizedChartRows(rows, fields).slice(0, 12)
  if (sampleRows.length < 2) return {}
  const values = sampleRows.flatMap((item) => fields.map((field) => item[field]))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  return Object.fromEntries(fields.map((field) => [field, polylineFromValues(sampleRows, field, min, span)]))
}

export function chartPolylinePoints(rows, field) {
  return comparisonChartPolylinePoints(rows, [field])[field] || ''
}

export function demoRowsFromDelivery(data) {
  if (Array.isArray(data?.sample_rows) && data.sample_rows.length) return data.sample_rows
  const features = data?.input_schema?.features || data?.required_features || []
  const dtypes = data?.input_schema?.dtypes || {}
  const row = {}
  features.forEach((name) => {
    const dtype = String(dtypes[name] || '').toLowerCase()
    row[name] = dtype.includes('int') || dtype.includes('float') || dtype.includes('double') || dtype.includes('number') ? 0 : ''
  })
  return [row]
}

export function hasObjectContent(value) {
  return value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length > 0
}

export function strategyLabel(value) {
  return {
    light_tabular: '轻量表格建模',
    standard_tabular: '标准表格建模',
    deep_tabular: '深度表格建模',
    custom_research: '自定义研究流程',
  }[value] || value || '未生成策略'
}

export function searchDepthLabel(value) {
  return {
    none: '不调参',
    small: '小范围',
    bounded: '有边界',
    deep: '较深入',
  }[value] || valueOrDash(value)
}

export function reportDepthLabel(value) {
  return {
    brief: '简短',
    standard: '标准',
    detailed: '详细',
  }[value] || valueOrDash(value)
}

export function valueOrDash(value) {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

export function sameComparableTask(candidate, current) {
  if (!candidate || !current) return false
  const candidateDataset = candidate.dataset_filename || candidate.dataset_name || ''
  const currentDataset = current.dataset_filename || current.dataset_name || ''
  if (candidateDataset && currentDataset && candidateDataset === currentDataset) return true
  const candidateType = candidate.task_type || candidate.problem_type || ''
  const currentType = current.task_type || current.problem_type || ''
  return Boolean(candidateType && currentType && candidateType === currentType)
}

export function normalizeTokenUsage(value) {
  if (!value || typeof value !== 'object') return null
  const total = value.total && typeof value.total === 'object' ? value.total : value
  const inputTokens = positiveNumber(total.total_input_tokens ?? total.input_tokens ?? total.inputTokens)
  const outputTokens = positiveNumber(total.total_output_tokens ?? total.output_tokens ?? total.outputTokens)
  const cachedInputTokens = positiveNumber(total.cached_input_tokens ?? total.cachedInputTokens)
  const reasoningOutputTokens = positiveNumber(total.reasoning_output_tokens ?? total.reasoningOutputTokens)
  const explicitTotal = positiveNumber(total.total_tokens ?? total.totalTokens)
  const totalTokens = explicitTotal || inputTokens + outputTokens
  if (!totalTokens) return null
  return {
    ...value,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    cached_input_tokens: cachedInputTokens,
    reasoning_output_tokens: reasoningOutputTokens,
    total_tokens: totalTokens,
  }
}

export function buildTokenComparison(currentUsage, peerTasks, currentTask) {
  const currentTotal = Number((currentUsage || {}).total_tokens || 0)
  const related = (Array.isArray(peerTasks) ? peerTasks : [])
    .filter((item) => item.id !== currentTask?.id)
    .filter((item) => sameComparableTask(item, currentTask))
    .map((item) => Number(item.llm_usage?.total_tokens || 0))
    .filter((value) => value > 0)
  if (!currentTotal || !related.length) {
    return {
      available: false,
      text: '暂无可比较的历史同类任务 token 记录。',
    }
  }
  const average = Math.round(related.reduce((sum, value) => sum + value, 0) / related.length)
  const diffRatio = average > 0 ? (currentTotal - average) / average : 0
  const direction = diffRatio > 0.08 ? '高于' : diffRatio < -0.08 ? '低于' : '接近'
  return {
    available: true,
    text: `当前 ${formatTokenCount(currentTotal)}，历史同类均值 ${formatTokenCount(average)}，${direction}均值。`,
    current: currentTotal,
    average,
    sample_count: related.length,
  }
}

export function buildTokenObservability({ usage, limits = {}, threadId = '', comparison = null } = {}) {
  const totalTokens = Number(usage?.total_tokens || 0)
  const inputTokens = Number(usage?.input_tokens || 0)
  const outputTokens = Number(usage?.output_tokens || 0)
  const cachedInputTokens = Math.min(inputTokens, Number(usage?.cached_input_tokens || 0))
  const uncachedInputTokens = Math.max(0, inputTokens - cachedInputTokens)
  const reasoningOutputTokens = Math.min(outputTokens, Number(usage?.reasoning_output_tokens || 0))
  const reasons = tokenObservabilityReasons({ totalTokens, limits, threadId })
  return {
    totalTokens,
    inputTokens,
    outputTokens,
    cachedInputTokens,
    uncachedInputTokens,
    reasoningOutputTokens,
    totalText: formatTokenCount(totalTokens),
    inputText: formatTokenCount(inputTokens),
    outputText: formatTokenCount(outputTokens),
    cachedInputText: formatTokenCount(cachedInputTokens),
    uncachedInputText: formatTokenCount(uncachedInputTokens),
    reasoningOutputText: formatTokenCount(reasoningOutputTokens),
    reasons,
    comparison,
  }
}

function tokenObservabilityReasons({ totalTokens, limits, threadId }) {
  const reasons = []
  if (!totalTokens) reasons.push('当前任务还没有真实 token 用量记录。')
  if (limits.allow_subagents || (Array.isArray(limits.planned_subagents) && limits.planned_subagents.length)) reasons.push('策略允许 subagents，会增加独立上下文、工具调用和汇总成本。')
  if (Number(limits.candidate_model_count || 0) > 3) reasons.push('候选模型数量较多，模型比较和结果解释会增加消耗。')
  if (Number(limits.max_auto_improvement_rounds || 0) > 1) reasons.push('允许多轮自动改进，失败诊断和重试会增加消耗。')
  if (limits.report_depth === 'detailed') reasons.push('报告深度为 detailed，最终报告和诊断说明会更长。')
  if (threadId) reasons.push('Codex thread 会累计历史上下文，新轮恢复会读取已有计划和产物。')
  if (totalTokens && !reasons.length) reasons.push('当前策略边界较轻，主要消耗来自计划、执行日志和最终报告。')
  return reasons
}

function positiveNumber(value) {
  const numeric = Number(value || 0)
  return Number.isFinite(numeric) && numeric > 0 ? numeric : 0
}
