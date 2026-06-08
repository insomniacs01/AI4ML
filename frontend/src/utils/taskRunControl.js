const CODEX_INTERRUPTED_STATUSES = new Set(['interrupted'])
const CODEX_PLAN_APPROVAL_STATUSES = new Set(['waiting_plan_approval', 'plan_ready', 'awaiting_plan_approval'])
const STEP_WAITING_HUMAN_STATUSES = new Set(['waiting_human', 'waiting', 'paused_for_review'])

export function continueRunOptions(task, taskRun, options = {}) {
  const taskStatus = statusValue(task?.status)
  const waitingForPlanApproval = isWaitingForPlanApproval(task, taskRun)
  const interrupted = isInterrupted(task, taskRun)
  const resumeAfterHuman = taskStatus === 'waiting_human' || waitingForPlanApproval
  return {
    resume_after_human: resumeAfterHuman,
    resume_interrupted: taskStatus === 'paused_for_review' && interrupted && !resumeAfterHuman,
    plan_text: resumeAfterHuman ? (options.planText || null) : null,
  }
}

function isInterrupted(task, taskRun) {
  const values = [
    task?.codex_status,
    task?.structured_requirements?.codex?.status,
    taskRun?.codex?.status,
    taskRun?.codex?.progress?.status,
    taskRun?.codex?.progress?.current_step,
    taskRun?.progress?.status,
    taskRun?.progress?.current_step,
  ]
  return values.map(statusValue).some((value) => CODEX_INTERRUPTED_STATUSES.has(value))
}

function isWaitingForPlanApproval(task, taskRun) {
  const statusValues = [
    task?.codex_status,
    task?.structured_requirements?.codex?.status,
    taskRun?.codex?.status,
    taskRun?.codex?.progress?.status,
    taskRun?.progress?.status,
  ]
  if (statusValues.map(statusValue).some((value) => CODEX_PLAN_APPROVAL_STATUSES.has(value))) {
    return true
  }
  return runtimeSteps(taskRun).some((step) => {
    const stepStatus = statusValue(step?.status)
    if (CODEX_PLAN_APPROVAL_STATUSES.has(stepStatus)) {
      return true
    }
    if (!STEP_WAITING_HUMAN_STATUSES.has(stepStatus)) {
      return false
    }
    return [step?.id, step?.name].map(statusValue).some((value) => CODEX_PLAN_APPROVAL_STATUSES.has(value))
  })
}

function runtimeSteps(taskRun) {
  const steps = [
    ...(Array.isArray(taskRun?.steps) ? taskRun.steps : []),
    ...(Array.isArray(taskRun?.codex?.steps) ? taskRun.codex.steps : []),
    ...(Array.isArray(taskRun?.progress?.steps) ? taskRun.progress.steps : []),
    ...(Array.isArray(taskRun?.codex?.progress?.steps) ? taskRun.codex.progress.steps : []),
  ]
  return steps.filter((step) => step && typeof step === 'object')
}

function statusValue(value) {
  return String(value || '').trim().toLowerCase()
}
