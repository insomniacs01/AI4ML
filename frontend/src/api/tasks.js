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
import { getActiveTeamHint, getCachedUser, requireSession } from '@/api/session'
import { getModelDisplayName } from '@/utils/modelProfile'
import { pickActiveTask, pickBlockingRuntimeTask, taskIdOf } from '@/utils/taskRecords'
import { clearTaskListCache, isTaskListCacheFresh, readTaskListCache, writeTaskListCache } from '@/utils/taskListCache'

let pendingDatasetFile = null
let pendingDatasetMeta = null
const RUNTIME_TASK_CACHE_PREFIX = 'ai4ml-runtime-task-list-cache-v1'
const RUNTIME_TASK_CACHE_TTL_MS = 3000
const pendingTaskListRequests = new Map()

function taskListCacheContext() {
  const userId = getCachedUser()?.id
  const teamId = getActiveTeamHint()?.id
  return userId && teamId ? { userId, teamId } : null
}

function invalidateTaskListCache() {
  clearTaskListCache(taskListCacheContext())
  clearRuntimeTaskListCache(taskListCacheContext())
}

function taskListContextKey(context = taskListCacheContext()) {
  return context ? `${context.userId}:${context.teamId}` : ''
}

function runtimeTaskCacheKey(context = taskListCacheContext()) {
  const key = taskListContextKey(context)
  return key ? `${RUNTIME_TASK_CACHE_PREFIX}:${key}` : ''
}

function readRuntimeTaskListCache(context = taskListCacheContext()) {
  const key = runtimeTaskCacheKey(context)
  if (!key || typeof localStorage === 'undefined') return null
  try {
    const cached = JSON.parse(localStorage.getItem(key) || 'null')
    if (!cached || Date.now() - Number(cached.cachedAt || 0) >= RUNTIME_TASK_CACHE_TTL_MS) return null
    return Array.isArray(cached.tasks) ? cached.tasks : null
  } catch {
    return null
  }
}

function writeRuntimeTaskListCache(context, tasks) {
  const key = runtimeTaskCacheKey(context)
  if (!key || typeof localStorage === 'undefined') return
  localStorage.setItem(key, JSON.stringify({
    cachedAt: Date.now(),
    tasks: Array.isArray(tasks) ? tasks : [],
  }))
}

function clearRuntimeTaskListCache(context = taskListCacheContext()) {
  const key = runtimeTaskCacheKey(context)
  if (!key || typeof localStorage === 'undefined') return
  localStorage.removeItem(key)
}

function pendingTaskListKey(context, query) {
  return `${taskListContextKey(context) || 'anonymous'}:${query || 'all'}`
}

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

export async function getTasks(options = {}) {
  const context = taskListCacheContext()
  if (options.runtimeOnly && !options.forceRefresh) {
    const cached = readRuntimeTaskListCache(context)
    if (cached) return { items: cached }
  }
  if (!options.runtimeOnly && !options.forceRefresh) {
    const cached = readTaskListCache(context)
    if (cached && isTaskListCacheFresh(cached.cachedAt)) return { items: cached.tasks || [] }
  }
  const params = new URLSearchParams()
  if (options.runtimeOnly) params.set('runtime_only', 'true')
  if (!options.runtimeOnly && options.compact !== false) params.set('compact', 'true')
  const query = params.toString()
  const requestKey = pendingTaskListKey(context, query)
  if (pendingTaskListRequests.has(requestKey)) return pendingTaskListRequests.get(requestKey)
  const taskListRequest = request(`/tasks${query ? `?${query}` : ''}`)
    .then((data) => {
      const items = (data.items || []).map(mapTask)
      if (options.runtimeOnly) writeRuntimeTaskListCache(context, items)
      else writeTaskListCache(context, items)
      return { items }
    })
    .finally(() => {
      pendingTaskListRequests.delete(requestKey)
    })
  pendingTaskListRequests.set(requestKey, taskListRequest)
  return taskListRequest
}

export async function getMyTasks(options = {}) {
  const userId = (getCachedUser() || (await requireSession()).user)?.id
  const data = await getTasks(options)
  return data.items.filter((task) => !task.created_by || task.created_by === userId)
}

export async function getWorkspaceTasks() {
  return getMyTasks({ runtimeOnly: true })
}

export async function getActiveTask(options = {}) {
  const tasks = await getMyTasks(options)
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
  const activeTask = await getActiveTask({ forceRefresh: true })
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
    result = await request(`/tasks/${task.id}/run?async_start=true`, {
      method: 'POST',
      body: JSON.stringify(runPayload),
    })
  }
  pendingDatasetFile = null
  pendingDatasetMeta = null
  invalidateTaskListCache()
  return mapTask(result)
}

export async function getTaskDetail(taskId) {
  const task = await request(`/tasks/${taskId}`)
  return detailFromTask(task)
}

export async function getTaskRuntimeSnapshot(taskId, options = {}) {
  const params = new URLSearchParams()
  if (options.sync === false) params.set('sync', 'false')
  if (options.taskDetail === 'summary') params.set('task_detail', 'summary')
  const query = params.toString()
  const snapshot = await request(`/tasks/${taskId}/runtime-snapshot${query ? `?${query}` : ''}`)
  const task = mapTask(snapshot.task)
  const taskRun = snapshot.task_run || {}
  const inferredMetrics = metricsFromTask(task, taskRun).values
  const taskRunMetrics = Object.keys(taskRun.metrics || {}).length ? taskRun.metrics : inferredMetrics
  const codexSteps = buildCodexSteps(taskRun.codex)
  const rawSteps = codexSteps.length
    ? codexSteps
    : Array.isArray(taskRun.steps)
      ? taskRun.steps.map(mapStageRecord)
      : buildSteps(task)
  return {
    task,
    task_run: {
      ...taskRun,
      metrics: taskRunMetrics,
      codex: taskRun.codex || null,
      steps: suppressClosedHumanSteps(taskRun, rawSteps),
    },
  }
}

function suppressClosedHumanSteps(taskRun, steps) {
  const hasExplicitOpenCount = Object.prototype.hasOwnProperty.call(taskRun || {}, 'open_request_count')
  if (!hasExplicitOpenCount || Number(taskRun.open_request_count || 0) > 0) return steps
  return steps.map((step) => (
    step?.status === 'waiting_human' ? { ...step, status: 'pending' } : step
  ))
}

export async function getCodexPlan(taskId) {
  return request(`/tasks/${taskId}/codex-plan`)
}

export async function deleteTask(taskId) {
  const result = await request(`/tasks/${taskId}`, { method: 'DELETE' })
  invalidateTaskListCache()
  return result
}

export async function cancelTask(taskId) {
  const task = await request(`/tasks/${taskId}/cancel`, { method: 'POST', body: JSON.stringify({}) })
  invalidateTaskListCache()
  return { ...mapTask(task), status: mapStatus(task.status) }
}

export async function pauseTask(taskId) {
  const task = await request(`/tasks/${taskId}/pause`, { method: 'POST', body: JSON.stringify({}) })
  invalidateTaskListCache()
  return { ...mapTask(task), status: mapStatus(task.status) }
}

export async function getMetrics(taskId) {
  const detail = await getTaskRuntimeSnapshot(taskId, { sync: false, taskDetail: 'summary' })
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
  const detail = await getTaskRuntimeSnapshot(taskId, { sync: false, taskDetail: 'summary' })
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
  const shouldRunAsync = Boolean(options.resume_after_human || options.resume_interrupted || options.regenerate_plan)
  const runPath = shouldRunAsync ? `/tasks/${taskId}/run?async_start=true` : `/tasks/${taskId}/run`
  const result = await request(runPath, {
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
  invalidateTaskListCache()
  return result
}
