const HUMAN_WAITING_STATUSES = new Set([
  'waiting_human',
  'waiting_plan_approval',
  'plan_ready',
  'awaiting_plan_approval',
])

const FINISHED_TASK_STATUSES = new Set(['completed', 'failed', 'cancelled', 'published'])
const OPEN_REQUEST_STATUSES = new Set(['pending', 'open'])

function statusValue(value) {
  return String(value || '').trim().toLowerCase()
}

export function isHumanWaitingStatus(value) {
  return HUMAN_WAITING_STATUSES.has(statusValue(value))
}

export function firstWaitingHumanStep(steps = []) {
  if (!Array.isArray(steps)) return null
  return steps.find((step) => isHumanWaitingStatus(step?.status)) || null
}

function hasOpenRequestCount(source) {
  const counts = [source?.open_request_count, source?.my_open_request_count]
  return counts.some((value) => Number(value || 0) > 0)
}

function hasOpenRequestList(source) {
  const requests = [
    ...(Array.isArray(source?.requests) ? source.requests : []),
    ...(Array.isArray(source?.my_requests) ? source.my_requests : []),
  ]
  return requests.some((request) => OPEN_REQUEST_STATUSES.has(statusValue(request?.status)))
}

function hasOpenHumanRequest(source) {
  return hasOpenRequestCount(source) || hasOpenRequestList(source)
}

function taskRunHasHumanWaitingStatus(taskRun) {
  const values = [
    taskRun?.progress_status,
    taskRun?.progress?.status,
    taskRun?.progress?.current_step,
    taskRun?.codex?.status,
    taskRun?.codex?.progress?.status,
    taskRun?.codex?.progress?.current_step,
  ]
  return values.some(isHumanWaitingStatus)
}

function taskRunSteps(taskRun) {
  return [
    ...(Array.isArray(taskRun?.steps) ? taskRun.steps : []),
    ...(Array.isArray(taskRun?.codex?.steps) ? taskRun.codex.steps : []),
    ...(Array.isArray(taskRun?.progress?.steps) ? taskRun.progress.steps : []),
    ...(Array.isArray(taskRun?.codex?.progress?.steps) ? taskRun.codex.progress.steps : []),
  ]
}

export function hasPendingHumanConfirmation(task, taskRun = null, steps = []) {
  const taskStatus = statusValue(task?.status)
  const hasOpenRequest = hasOpenHumanRequest(task) || hasOpenHumanRequest(taskRun)
  if (FINISHED_TASK_STATUSES.has(taskStatus)) return hasOpenRequest
  return (
    isHumanWaitingStatus(taskStatus)
    || hasOpenRequest
    || taskRunHasHumanWaitingStatus(taskRun)
    || Boolean(firstWaitingHumanStep(steps))
    || Boolean(firstWaitingHumanStep(taskRunSteps(taskRun)))
  )
}
