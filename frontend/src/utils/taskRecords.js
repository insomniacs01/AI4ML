export const ACTIVE_TASK_STATUSES = new Set(['uploaded', 'planning', 'pending', 'queued', 'running', 'waiting_human', 'paused_for_review'])
export const BLOCKING_RUNTIME_TASK_STATUSES = new Set(['pending', 'queued', 'running'])

const ACTIVE_TASK_PRIORITY = {
  running: 0,
  pending: 1,
  queued: 2,
  waiting_human: 3,
  paused_for_review: 4,
  planning: 5,
  uploaded: 6,
}

export function taskIdOf(task) {
  return task?.task_id || task?.id || ''
}

export function taskTimestamp(task, field) {
  const value = Date.parse(task?.[field] || '')
  return Number.isFinite(value) ? value : 0
}

export function compareActiveTasks(leftTask, rightTask) {
  const left = activeTaskSortKey(leftTask)
  const right = activeTaskSortKey(rightTask)
  for (let index = 0; index < left.length; index += 1) {
    if (left[index] !== right[index]) return left[index] - right[index]
  }
  return 0
}

export function pickActiveTask(tasks = []) {
  return [...tasks]
    .filter((task) => ACTIVE_TASK_STATUSES.has(task?.status))
    .sort(compareActiveTasks)[0] || null
}

export function pickBlockingRuntimeTask(tasks = []) {
  return [...tasks]
    .filter((task) => BLOCKING_RUNTIME_TASK_STATUSES.has(task?.status))
    .sort(compareActiveTasks)[0] || null
}

export function isFinishedTaskStatus(status) {
  return ['completed', 'failed', 'cancelled'].includes(status)
}

export function stepStatusLabel(status) {
  return {
    completed: '完成',
    success: '完成',
    failed: '失败',
    cancelled: '已取消',
    running: '运行中',
    paused_for_review: '已暂停',
    waiting_human: '待确认',
    pending: '等待',
    planning: '待启动',
    uploaded: '待启动',
  }[status] || status || '等待'
}

function activeTaskSortKey(task) {
  return [
    ACTIVE_TASK_PRIORITY[task?.status] ?? 9,
    -taskTimestamp(task, 'created_at'),
    -taskTimestamp(task, 'updated_at'),
  ]
}
