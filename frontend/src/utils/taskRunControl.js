const CODEX_INTERRUPTED_STATUSES = new Set(['interrupted'])
const CODEX_PLAN_APPROVAL_STATUSES = new Set(['waiting_plan_approval', 'plan_ready', 'awaiting_plan_approval'])

export function continueRunOptions(task, taskRun, options = {}) {
  const taskStatus = statusValue(task?.status)
  const values = runtimeStatusValues(task, taskRun)
  const waitingForPlanApproval = values.some((value) => CODEX_PLAN_APPROVAL_STATUSES.has(value))
  const interrupted = values.some((value) => CODEX_INTERRUPTED_STATUSES.has(value))
  const resumeAfterHuman = taskStatus === 'waiting_human' || waitingForPlanApproval
  return {
    resume_after_human: resumeAfterHuman,
    resume_interrupted: taskStatus === 'paused_for_review' && interrupted && !resumeAfterHuman,
    plan_text: resumeAfterHuman ? (options.planText || null) : null,
  }
}

function runtimeStatusValues(task, taskRun) {
  const values = [
    task?.codex_status,
    task?.structured_requirements?.codex?.status,
    taskRun?.codex?.status,
    taskRun?.codex?.progress?.status,
    taskRun?.codex?.progress?.current_step,
    taskRun?.progress?.status,
    taskRun?.progress?.current_step,
  ]
  const steps = [
    ...(Array.isArray(taskRun?.steps) ? taskRun.steps : []),
    ...(Array.isArray(taskRun?.codex?.steps) ? taskRun.codex.steps : []),
    ...(Array.isArray(taskRun?.progress?.steps) ? taskRun.progress.steps : []),
    ...(Array.isArray(taskRun?.codex?.progress?.steps) ? taskRun.codex.progress.steps : []),
  ]
  steps.forEach((step) => {
    values.push(step?.id, step?.name, step?.status)
  })
  return values.map(statusValue).filter(Boolean)
}

function statusValue(value) {
  return String(value || '').trim().toLowerCase()
}
