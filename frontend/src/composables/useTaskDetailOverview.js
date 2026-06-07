import { computed } from 'vue'
import { checkLabel, featureLabel, formatMetricValue } from '@/utils/formatters'
import { metricLabel } from '@/utils/labels'
import { renderMarkdown } from '@/utils/markdown'
import { modelDisplayName } from '@/utils/modelProfile'
import { hasPendingHumanConfirmation } from '@/utils/taskHumanState'

function addMetricValues(target, source, prefix = '') {
  Object.entries(source || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === '') return
    const label = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'number' || typeof value === 'string') {
      target[label] = value
      return
    }
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      addMetricValues(target, value, label)
    }
  })
}

function targetSummariesFromOverview(value) {
  const summary = value?.task_summary || {}
  const rawTargets = summary.target_columns || summary.targets || value?.target_columns || value?.targets || []
  const targetMetrics = value?.target_metrics || value?.metrics_by_target || summary.target_metrics || {}
  const names = Array.isArray(rawTargets)
    ? rawTargets.map((item) => (typeof item === 'string' ? item : item?.name || item?.target || item?.column)).filter(Boolean)
    : Object.keys(targetMetrics)
  return names.map((name) => {
    const metrics = targetMetrics?.[name] || {}
    const firstMetric = Object.entries(metrics).find(([, item]) => item !== null && item !== undefined && item !== '')
    return {
      name,
      metric: firstMetric?.[0] || '',
      value: firstMetric ? formatMetricValue(firstMetric[1]) : '',
    }
  })
}

export function useTaskDetailOverview({ task, taskRun, metrics, importance, overview, report, planText }) {
  const waitingHuman = computed(() => hasPendingHumanConfirmation(task.value, taskRun.value, taskRun.value?.steps || []))
  const effectiveMetrics = computed(() => {
    const values = {}
    addMetricValues(values, metrics.value?.values || {})
    addMetricValues(values, taskRun.value?.metrics || {})
    addMetricValues(values, task.value?.metrics || {})
    const artifacts = taskRun.value?.artifacts || {}
    if (artifacts.metric_name && artifacts.metric_value != null) values[artifacts.metric_name] = artifacts.metric_value
    if (task.value?.metric && task.value?.last_run?.metric_value != null) values[task.value.metric] = task.value.last_run.metric_value
    const bestRow = Array.isArray(task.value?.leaderboard) ? task.value.leaderboard[0] : null
    const bestMetricName = bestRow?.metric_name || bestRow?.metric || task.value?.metric || artifacts.metric_name
    const bestMetricValue = bestRow?.metric_value ?? bestRow?.validation_score ?? bestRow?.score
    if (!Object.keys(values).length && bestMetricName && bestMetricValue != null) values[bestMetricName] = bestMetricValue
    return values
  })
  const effectiveOverview = computed(() => overview.value || taskRun.value?.overview || {})
  const metricEntries = computed(() =>
    Object.entries(effectiveMetrics.value)
      .filter(([, value]) => value !== null && value !== undefined && value !== '')
      .map(([key, value]) => ({ key, label: metricLabel(key), value: formatMetricValue(value) }))
  )
  const topFeatures = computed(() => {
    const raw = effectiveOverview.value?.key_factors?.length
      ? effectiveOverview.value.key_factors
      : importance.value?.items || importance.value?.feature_importance || importance.value?.features || []
    if (!Array.isArray(raw)) return []
    const items = raw
      .map((item) => {
        const numericValue = Number(item.importance ?? item.value ?? item.score)
        return {
          name: item.feature || item.name || item.display || '',
          value: Math.abs(numericValue),
          source: item.source || '',
          evidence: item.evidence || '',
          isModelFeatureImportance: item.is_model_feature_importance,
        }
      })
      .filter((item) => item.name && Number.isFinite(item.value) && item.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 8)
    const maxValue = Math.max(...items.map((item) => item.value), 0.000001)
    return items.map((item, index) => ({
      ...item,
      rank: index + 1,
      label: featureLabel(item.name),
      percent: Math.max(4, Math.round((item.value / maxValue) * 100)),
      displayValue: item.value.toFixed(item.value >= 1 ? 2 : 3),
      source: item.source,
      evidence: item.evidence,
      isModelFeatureImportance: item.isModelFeatureImportance,
    }))
  })
  const overviewPredictionError = computed(() => effectiveOverview.value?.prediction_error || {})
  const targetSummaries = computed(() => {
    const overviewTargets = targetSummariesFromOverview(effectiveOverview.value)
    if (overviewTargets.length) return overviewTargets
    const taskTargets = task.value?.target_columns || []
    return Array.isArray(taskTargets) ? taskTargets.map((name) => ({ name, metric: '', value: '' })) : []
  })
  const renderedReport = computed(() => renderMarkdown(report.value || '报告尚未生成。'))
  const planPreview = computed(() => {
    const normalized = String(planText.value || '').replace(/\s+/g, ' ').trim()
    if (!normalized) return `当前还没有加载到 ${modelDisplayName.value} 执行方案。`
    return normalized.length > 180 ? `${normalized.slice(0, 180)}...` : normalized
  })
  const primaryMetric = computed(() => {
    const predictionError = overviewPredictionError.value
    if (predictionError?.primary_metric && predictionError.value !== null && predictionError.value !== undefined) {
      return {
        key: predictionError.primary_metric,
        label: metricLabel(predictionError.primary_metric),
        value: predictionError.display || formatMetricValue(predictionError.value),
      }
    }
    return metricEntries.value[0] || null
  })
  const overviewConclusion = computed(() => {
    const conclusion = effectiveOverview.value?.task_summary?.conclusion
    if (conclusion) return conclusion
    if (!task.value) return '等待任务数据加载'
    if (task.value.status === 'completed') return '已生成可读报告'
    if (task.value.status === 'failed') return '运行遇到问题'
    if (waitingHuman.value) return '等待人工确认'
    if (task.value.status === 'paused_for_review') return '运行已暂停'
    if (task.value.status === 'running') return '等待生成可读报告'
    return '等待开始运行'
  })
  const overviewCheckItems = computed(() => {
    const checks = effectiveOverview.value?.result_checks
    if (Array.isArray(checks) && checks.length) {
      return checks.slice(0, 6).map((item) => ({
        label: checkLabel(item.name),
        value: item.detail || item.status || '已记录',
      }))
    }
    return [
      {
        label: '结果检查',
        value: '未生成结构化检查记录。',
      },
    ]
  })
  const overviewBadges = computed(() => {
    const checks = effectiveOverview.value?.result_checks || []
    const records = effectiveOverview.value?.optimization_records || []
    if (checks.length || records.length) {
      const failed = checks.filter((item) => item.status === 'failed').length
      const warnings = checks.filter((item) => item.status === 'warning').length
      return [
        failed ? `${failed} 项未通过` : '检查已记录',
        records.length ? `优化记录 ${records.length} 条` : '无优化记录',
        warnings ? `${warnings} 项需复核` : '无严重警告',
      ]
    }
    if (task.value?.status === 'completed') return ['结果已生成', '可查看报告']
    if (waitingHuman.value) return ['需要人工确认', '确认后继续运行']
    if (task.value?.status === 'failed') return ['运行遇到问题', '需要查看诊断']
    return ['任务语义可执行', '等待完成运行']
  })
  const overviewFactors = computed(() => {
    if (topFeatures.value.length) {
      return topFeatures.value.slice(0, 4).map((item) => ({
        label: item.label,
        percent: item.percent,
      }))
    }
    return []
  })
  const overviewFactorDescription = computed(() => {
    if (!topFeatures.value.length) return '当前任务没有返回真实特征重要性或诊断因素。'
    if (topFeatures.value.some((item) => item.isModelFeatureImportance === false)) {
      return '当前展示的是误差分析或诊断因素，不等同于模型特征重要性。'
    }
    return '这些是真实模型解释返回的关键特征。'
  })
  return {
    effectiveOverview,
    targetSummaries,
    renderedReport,
    planPreview,
    primaryMetric,
    overviewConclusion,
    overviewCheckItems,
    overviewBadges,
    overviewFactors,
    overviewFactorDescription,
  }
}
