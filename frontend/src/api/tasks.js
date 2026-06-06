import {
  buildCodexSteps,
  buildSteps,
  detailFromTask,
  mapStageRecord,
  mapStatus,
  mapTask,
  metricsFromTask,
} from '@/api/mappers'
import { optionalRequest, request } from '@/api/request'
import { getCachedUser, requireSession } from '@/api/session'
import { getModelDisplayName } from '@/utils/modelProfile'
import { pickActiveTask, pickBlockingRuntimeTask, taskIdOf } from '@/utils/taskRecords'
export { getOperationCode, updateOperationCode, validateOperationCode } from '@/api/taskCodeArtifacts'
export { getDelivery, getPublicDemo, predict, predictPublicDemo } from '@/api/taskPredictionDemo'
export { getHitl, submitHitl } from '@/api/taskHuman'

let pendingDatasetFile = null
let pendingDatasetMeta = null

function firstCsvFile(formData) {
  return formData?.get('dataset_file') || formData?.get('file') || null
}

function readForm(formData, key, fallback = '') {
  return String(formData?.get(key) ?? fallback).trim()
}

function targetColumnsFromText(value) {
  return String(value || '')
    .split(/[，,;；|\n\r\t]+/)
    .map((item) => item.trim().replace(/^["'`]+|["'`]+$/g, ''))
    .filter(Boolean)
    .filter((item, index, list) => list.indexOf(item) === index)
}

function isFileValue(value) {
  return typeof File !== 'undefined' && value instanceof File
}

function buildInteractionPolicies(formData) {
  const enabled = String(formData?.get('enable_hitl') ?? 'false') === 'true'
  const currentUser = getCachedUser()
  if (!enabled || !currentUser?.id) return []
  return [
    {
      policy_id: 'before-run-human-confirmation',
      enabled: true,
      stage: 'training_validation',
      trigger_mode: 'before_run',
      assignee_type: 'member',
      assignee_value: currentUser.id,
      request_type: 'stage_checkpoint',
      title: 'Confirm before training',
      summary: 'Confirm the target column, task type, metric, and training budget before running.',
      suggested_action: `Confirm and continue ${getModelDisplayName()} execution.`,
      timeout_minutes: 1440,
      artifact_paths: [],
    },
  ]
}

function createTaskPayloadFromForm(formData) {
  const requirement = readForm(formData, 'requirement', 'Train a model from the uploaded dataset and generate a readable report.')
  const targetColumn = readForm(formData, 'target_column')
  const targetColumns = targetColumnsFromText(targetColumn)
  const taskType = readForm(formData, 'task_type')
  const metricName = readForm(formData, 'metric')
  const name = requirement.length > 36 ? `${requirement.slice(0, 36)}...` : requirement
  const selectedPlanText = readForm(formData, 'selected_plan_text')
  const selectedPlanId = readForm(formData, 'selected_plan_id')
  const selectedPlanName = readForm(formData, 'selected_plan_name')
  const structuredRequirements = {}
  if (selectedPlanText) {
    structuredRequirements.selected_plan = {
      plan_text: selectedPlanText,
      plan_id: selectedPlanId || null,
      plan_name: selectedPlanName || null,
      source: selectedPlanId ? 'community_plan' : 'manual_plan',
    }
  }
  if (targetColumn) {
    structuredRequirements.target_hint = targetColumn
    structuredRequirements.target_columns_hint = targetColumns
    structuredRequirements.target_definition = {
      target_mode: targetColumns.length > 1 ? 'multi_target' : 'single_target',
      target_columns: targetColumns,
      source: 'user_input',
    }
  }
  if (metricName) structuredRequirements.metric_name = metricName
  return {
    name: name || '智能建模实验',
    description: requirement,
    label_column: targetColumns.length <= 1 ? (targetColumn || null) : null,
    problem_type: ['classification', 'regression'].includes(taskType) ? taskType : null,
    structured_requirements: Object.keys(structuredRequirements).length ? structuredRequirements : null,
    stage_routing: [],
    interaction_policies: buildInteractionPolicies(formData),
  }
}

function displayTaskName(task) {
  return task?.display_name || task?.name || task?.requirement || '未命名任务'
}

export async function getTasks() {
  const data = await request('/tasks')
  return { items: (data.items || []).map(mapTask) }
}

export async function getMyTasks() {
  const data = await getTasks()
  const cachedUser = getCachedUser()
  const userId = cachedUser?.id || (await requireSession()).user?.id
  return data.items.filter((task) => !task.created_by || task.created_by === userId)
}

export async function getActiveTask() {
  const tasks = await getMyTasks()
  return pickBlockingRuntimeTask(tasks)
}

export async function uploadDataset(formData) {
  pendingDatasetFile = firstCsvFile(formData)
  pendingDatasetMeta = Object.fromEntries([...formData.entries()].filter(([, value]) => !isFileValue(value)))
  if (!pendingDatasetFile) throw new Error('Please choose a dataset file first.')
  return {
    dataset_path: '__pending_local_upload__',
    name: pendingDatasetFile.name,
    size: pendingDatasetFile.size,
    meta: pendingDatasetMeta,
  }
}

export async function createTask(formData) {
  const activeTask = await getActiveTask()
  if (activeTask) {
    throw new Error(`已有任务正在运行：${displayTaskName(activeTask)}（${taskIdOf(activeTask)}）。请先在工作台处理、完成或取消该任务。`)
  }
  const task = await request('/tasks', {
    method: 'POST',
    body: JSON.stringify(createTaskPayloadFromForm(formData)),
  })
  let result = task
  const file = pendingDatasetFile || firstCsvFile(formData)
  if (file) {
    const uploadBody = new FormData()
    uploadBody.append('file', file)
    const timeLimit = Number(readForm(formData, 'time_budget_s', '20'))
    const query = new URLSearchParams({ auto_run: 'false' })
    if (Number.isFinite(timeLimit) && timeLimit >= 5) query.set('time_limit', String(Math.min(300, timeLimit)))
    result = await request(`/tasks/${task.id}/dataset?${query}`, { method: 'POST', body: uploadBody })
    const runPayload = Number.isFinite(timeLimit) && timeLimit >= 5 ? { time_limit: Math.min(300, timeLimit) } : {}
    result = await request(`/tasks/${task.id}/run`, {
      method: 'POST',
      body: JSON.stringify(runPayload),
    })
  }
  pendingDatasetFile = null
  pendingDatasetMeta = null
  return mapTask(result)
}

export async function getTaskDetail(taskId) {
  const task = await request(`/tasks/${taskId}`)
  return detailFromTask(task)
}

export async function getTaskRuntimeSnapshot(taskId, options = {}) {
  const query = options.sync === false ? '?sync=false' : ''
  const snapshot = await request(`/tasks/${taskId}/runtime-snapshot${query}`)
  const task = mapTask(snapshot.task)
  const taskRun = snapshot.task_run || {}
  const inferredMetrics = metricsFromTask(task, taskRun).values
  const taskRunMetrics = Object.keys(taskRun.metrics || {}).length ? taskRun.metrics : inferredMetrics
  const codexSteps = buildCodexSteps(taskRun.codex)
  return {
    task,
    task_run: {
      ...taskRun,
      metrics: taskRunMetrics,
      codex: taskRun.codex || null,
      steps: codexSteps.length
        ? codexSteps
        : Array.isArray(taskRun.steps)
          ? taskRun.steps.map(mapStageRecord)
          : buildSteps(task),
    },
  }
}

export async function deleteTask(taskId) {
  return request(`/tasks/${taskId}`, { method: 'DELETE' })
}

export async function cancelTask(taskId) {
  const task = await request(`/tasks/${taskId}/cancel`, { method: 'POST', body: JSON.stringify({}) })
  return { ...mapTask(task), status: mapStatus(task.status) }
}

export async function pauseTask(taskId) {
  const task = await request(`/tasks/${taskId}/pause`, { method: 'POST', body: JSON.stringify({}) })
  return { ...mapTask(task), status: mapStatus(task.status) }
}

export async function getMetrics(taskId) {
  const detail = await getTaskRuntimeSnapshot(taskId)
  const taskRunMetrics = detail.task_run?.metrics || {}
  return Object.keys(taskRunMetrics).length
    ? { values: taskRunMetrics }
    : metricsFromTask(detail.task, detail.task_run)
}

export async function getFeatureImportance(taskId) {
  const report = await optionalRequest(`/tasks/${taskId}/report`, {}, { feature_importance: [] })
  return { items: report.feature_importance || [], overview: report.overview || {} }
}

export async function getTaskOverview(taskId) {
  const detail = await getTaskRuntimeSnapshot(taskId)
  if (detail.task_run?.overview && Object.keys(detail.task_run.overview).length) {
    return detail.task_run.overview
  }
  const report = await optionalRequest(`/tasks/${taskId}/report`, {}, { overview: {} })
  return report.overview || {}
}

export async function getReport(taskId, reportType) {
  const report = await optionalRequest(`/tasks/${taskId}/report`, {}, { report_markdown: '' })
  return { content: report.report_markdown || '', report_type: reportType }
}

export async function rerunTask(taskId, adjustments, options = {}) {
  return request(`/tasks/${taskId}/run`, {
    method: 'POST',
    body: JSON.stringify({
      time_limit: adjustments?.time_budget_s || options.time_limit || null,
      rerun_from_stage: options.rerun_from_stage || null,
      force_full_run: Boolean(options.force_full_run),
      resume_after_human: Boolean(options.resume_after_human),
      resume_interrupted: Boolean(options.resume_interrupted),
      regenerate_plan: Boolean(options.regenerate_plan),
      improvement_decision: options.improvement_decision || null,
      plan_text: options.plan_text || null,
    }),
  })
}
