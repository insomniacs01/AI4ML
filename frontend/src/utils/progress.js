export function taskProgressPercent({ status, steps = [], isBootstrapping = false, progressPercent = null } = {}) {
  if (status === 'completed') return 100
  if (['draft', 'uploaded', 'planning'].includes(status)) return 0
  if (['waiting_human', 'paused_for_review'].includes(status)) return 25
  if (['failed', 'cancelled'].includes(status)) {
    return nonCompletionTerminalPercent(progressPercent, steps)
  }

  const backendPercent = Number(progressPercent)
  if (Number.isFinite(backendPercent) && backendPercent > 0) {
    return Math.min(99, Math.max(0, Math.round(backendPercent)))
  }
  if (isBootstrapping) return status === 'queued' ? 8 : 10

  const visibleSteps = Array.isArray(steps) ? steps : []
  if (!visibleSteps.length) return status === 'running' ? 14 : 0

  const done = visibleSteps.filter((step) => ['completed', 'success'].includes(step.status)).length
  const running = visibleSteps.some((step) => step.status === 'running') ? 1 : 0
  const waitingIndex = visibleSteps.findIndex((step) => step.status === 'waiting_human')
  const waiting = waitingIndex >= 0 ? 0.6 : 0
  const ratio = (done + running * 0.35 + waiting) / Math.max(visibleSteps.length, 1)
  const base = status === 'running' ? 18 : 12
  return Math.min(88, Math.max(base, Math.round(base + ratio * 62)))
}

function nonCompletionTerminalPercent(progressPercent, steps) {
  const backendPercent = Number(progressPercent)
  if (Number.isFinite(backendPercent) && backendPercent > 0 && backendPercent < 100) {
    return Math.max(0, Math.round(backendPercent))
  }

  const visibleSteps = Array.isArray(steps) ? steps : []
  if (!visibleSteps.length) return 0

  const done = visibleSteps.filter((step) => ['completed', 'success'].includes(step.status)).length
  const running = visibleSteps.some((step) => step.status === 'running') ? 1 : 0
  const waiting = visibleSteps.some((step) => ['waiting_human', 'paused_for_review'].includes(step.status)) ? 0.6 : 0
  const failed = visibleSteps.some((step) => ['failed', 'cancelled'].includes(step.status)) ? 0.8 : 0
  const ratio = (done + running * 0.35 + waiting + failed) / Math.max(visibleSteps.length, 1)
  return Math.min(99, Math.max(0, Math.round(ratio * 88)))
}
