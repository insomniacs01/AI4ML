export const WORKSPACE_TASK_STATUSES = new Set(['running', 'waiting_human', 'paused_for_review', 'planning', 'uploaded'])
export const BLOCKING_RUNTIME_TASK_STATUSES = new Set(['running'])

const WORKSPACE_TASK_PRIORITY = {
  running: 0,
  waiting_human: 1,
  paused_for_review: 2,
  planning: 3,
  uploaded: 4,
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
    .filter((task) => WORKSPACE_TASK_STATUSES.has(task?.status))
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
    WORKSPACE_TASK_PRIORITY[task?.status] ?? 9,
    -taskTimestamp(task, 'created_at'),
    -taskTimestamp(task, 'updated_at'),
  ]
}
