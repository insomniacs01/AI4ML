import { getModelDisplayName } from '@/utils/modelProfile'

const STAGE_ORDER = [
  'requirement_analysis',
  'data_analysis',
  'feature_engineering',
  'model_selection',
  'training_validation',
  'report_generation',
]

export const STAGE_LABELS = {
  requirement_analysis: 'Requirement analysis',
  data_analysis: 'Data analysis',
  feature_engineering: 'Feature engineering',
  model_selection: 'Model selection',
  training_validation: 'Training validation',
  report_generation: 'Report generation',
}

const CODEX_STATUS_MAP = {
  completed: 'completed',
  done: 'completed',
  success: 'completed',
  running: 'running',
  in_progress: 'running',
  executing: 'running',
  waiting: 'waiting_human',
  waiting_plan_approval: 'waiting_human',
  plan_ready: 'waiting_human',
  interrupted: 'failed',
  failed: 'failed',
  error: 'failed',
}

export function mapStatus(status) {
  return status || 'draft'
}

function displayStatusForTask(task) {
  const notes = String(task?.notes || '').toLowerCase()
  if (notes.includes('user cancelled task') || notes.includes('cancelled')) return 'cancelled'
  return mapStatus(task?.status)
}

function totalTokens(task) {
  const analysis = Number(task?.analysis_token_usage?.total_tokens || 0)
  const run = Number(task?.last_run?.token_usage?.total_tokens || task?.last_run_attempt?.token_usage?.total_tokens || 0)
  return analysis + run
}

export function mapTask(task) {
  if (!task) return task
  const run = task.last_run || null
  const metricName = run?.metric_name || task.structured_requirements?.metric_name || ''
  const metricValue = run?.metric_value
  return {
    ...task,
    id: task.id,
    task_id: task.id,
    user_id: task.created_by,
    display_name: task.name,
    name: task.name,
    requirement: task.description,
    task_type: task.problem_type || '',
    target_column: task.label_column || '',
    metric: metricName,
    status: displayStatusForTask(task),
    dataset_name: task.dataset_filename || '',
    created_at: task.created_at,
    updated_at: task.updated_at,
    llm_usage: {
      total_tokens: totalTokens(task),
      input_tokens: Number(task.analysis_token_usage?.input_tokens || 0) + Number((run?.token_usage || task?.last_run_attempt?.token_usage)?.input_tokens || 0),
      output_tokens: Number(task.analysis_token_usage?.output_tokens || 0) + Number((run?.token_usage || task?.last_run_attempt?.token_usage)?.output_tokens || 0),
    },
    metrics: metricName ? { [metricName]: metricValue } : {},
    leaderboard: run?.leaderboard || [],
    best_estimator: run?.best_model || '',
  }
}

export function mapAsset(asset) {
  if (!asset) return asset
  const type = asset.asset_type || 'prompt'
  const status = asset.review_status === 'private' ? 'draft' : asset.review_status
  const metadata = asset.metadata || {}
  const common = {
    ...asset,
    asset_id: asset.id,
    name: asset.title,
    description: asset.description,
    status,
    owner_id: asset.created_by,
    tags: asset.tags || [],
    task_category: asset.category || asset.metadata?.task_category || type,
    organization_id: '',
    like_count: 0,
    favorite_count: 0,
    comment_count: 0,
    suggestion_count: 0,
    liked_by_me: false,
    favorited_by_me: false,
  }
  if (type === 'plan') {
    return {
      ...common,
      plan_id: asset.id,
      plan_text: metadata.plan_text || '',
      executor_type: metadata.executor_type || 'codex',
      source_task_id: asset.source_task_id || metadata.source_task_id || '',
    }
  }
  return {
    ...common,
    prompt_id: asset.id,
    prompt_title: metadata.prompt_title || asset.title || '',
    prompt_description: metadata.prompt_description || asset.description || '',
    target_column: metadata.target_column || '',
    metric: metadata.metric || '',
  }
}

export function truncateText(value, maxLength) {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.length > maxLength ? text.slice(0, maxLength) : text
}

export function groupAssets(items = []) {
  return {
    prompts: items.filter((item) => item.asset_type === 'prompt').map(mapAsset),
    plans: items.filter((item) => item.asset_type === 'plan').map(mapAsset),
  }
}

function stageStatusFromTask(task, stage) {
  const status = mapStatus(task?.status)
  if (status === 'completed') return 'completed'
  if (status === 'failed') return ['feature_engineering', 'model_selection', 'training_validation'].includes(stage) ? 'failed' : 'completed'
  if (status === 'waiting_human') return stage === 'training_validation' ? 'waiting_human' : 'pending'
  if (status === 'paused_for_review') return ['feature_engineering', 'model_selection', 'training_validation'].includes(stage) ? 'waiting_human' : 'completed'
  if (status === 'running') return ['feature_engineering', 'model_selection', 'training_validation'].includes(stage) ? 'running' : (stage === 'report_generation' ? 'pending' : 'completed')
  if (status === 'uploaded' || status === 'planning') return ['requirement_analysis', 'data_analysis'].includes(stage) ? 'completed' : 'pending'
  return stage === 'requirement_analysis' ? 'completed' : 'pending'
}

export function mapStageRecord(record) {
  const stage = record.stage || record.name || record.node || 'requirement_analysis'
  return {
    id: record.id || stage,
    name: stage,
    node: stage,
    title: STAGE_LABELS[stage] || stage,
    agent_role: STAGE_LABELS[stage] || stage,
    status: record.status || 'pending',
    message: record.message || record.summary || record.log_excerpt || '',
    summary: record.summary || '',
    duration_s: record.duration_s ?? record.duration_seconds,
    artifacts: Array.isArray(record.artifacts)
      ? record.artifacts
      : (Array.isArray(record.artifact_refs) ? record.artifact_refs : (record.artifact_refs ? [record.artifact_refs] : [])),
    updated_at: record.updated_at,
  }
}

function mapCodexStep(record, index = 0) {
  const id = record?.id || `codex_step_${index + 1}`
  const status = CODEX_STATUS_MAP[record?.status] || record?.status || 'pending'
  const detail = record?.detail || record?.summary || record?.message || ''
  return {
    id,
    name: id,
    node: id,
    title: record?.title || id,
    agent_role: getModelDisplayName(),
    status,
    message: detail,
    summary: detail,
    duration_s: record?.duration_s || null,
    artifacts: Array.isArray(record?.artifacts) ? record.artifacts : [],
    updated_at: record?.updated_at || null,
  }
}

export function buildCodexSteps(codex) {
  if (!codex || !Array.isArray(codex.steps) || codex.steps.length === 0) return []
  return codex.steps.map(mapCodexStep)
}

export function buildSteps(task, progress = null, collaboration = null) {
  const codexSteps = buildCodexSteps(progress?.codex)
  if (codexSteps.length) return codexSteps
  const records = new Map()
  ;(collaboration?.stages || []).forEach((stage) => records.set(stage.stage, mapStageRecord(stage)))
  const steps = STAGE_ORDER.map((stage) => records.get(stage) || {
    id: stage,
    name: stage,
    node: stage,
    title: STAGE_LABELS[stage],
    agent_role: STAGE_LABELS[stage],
    status: stageStatusFromTask(task, stage),
    message: '',
    summary: '',
    artifacts: [],
  })

  if (progress) {
    const currentStage = progress.current_stage
    steps.forEach((step) => {
      if (step.name === currentStage && ['running', 'repairing', 'blocked', 'stale'].includes(progress.status)) {
        step.status = progress.status === 'blocked' ? 'waiting_human' : 'running'
        step.message = progress.current_activity || progress.observer_detail || step.message
      }
      if (step.name === 'training_validation' && progress.artifacts?.metric_name) {
        step.activity_items = [
          { kind: 'metric', label: progress.artifacts.metric_name, value: progress.artifacts.metric_value ?? '-' },
          { kind: 'model', label: 'Best model', value: progress.artifacts.best_model || '-' },
        ]
      }
    })
  }
  return steps
}

export function metricsFromTask(task, progress = null) {
  const run = task?.last_run
  const metricName = progress?.artifacts?.metric_name || run?.metric_name || task?.metric
  const metricValue = progress?.artifacts?.metric_value ?? run?.metric_value
  return metricName ? { values: { [metricName]: metricValue } } : { values: {} }
}

export function detailFromTask(task, progress = null, collaboration = null) {
  const mapped = mapTask(progress?.task || task)
  const progressPercent = Number(progress?.progress_percent)
  const codexSteps = buildCodexSteps(progress?.codex)
  return {
    task: mapped,
    task_run: {
      codex: progress?.codex || null,
      steps: codexSteps.length ? codexSteps : buildSteps(mapped, progress, collaboration),
      leaderboard: progress?.leaderboard || mapped?.leaderboard || [],
      metrics: metricsFromTask(mapped, progress).values,
      progress_percent: Number.isFinite(progressPercent) ? Math.max(0, Math.min(100, Math.round(progressPercent))) : null,
      current_stage: progress?.current_stage || null,
      current_activity: progress?.current_activity || '',
      progress_status: progress?.status || '',
    },
  }
}
