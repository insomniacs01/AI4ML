import { shouldApplyRealtimeTaskPatch } from './codexRealtime'

const RUNNING_EVENT_TYPES = new Set(['task_resume_requested', 'modeling_started', 'turn_started'])

export function workspaceRealtimeUpdate({
  payload,
  activeTask,
  taskRun,
  realtimeStatus,
  finished = false,
} = {}) {
  if (!payload || typeof payload !== 'object' || !activeTask) return null
  if (!shouldApplyRealtimeTaskPatch(payload, realtimeStatus)) return null
  if (finished && payload.type !== 'task_completed') return null

  if (payload.type === 'task_completed') {
    return {
      taskPatch: { status: 'completed', codex_status: 'completed' },
      taskRun: completedTaskRun(taskRun),
      persist: true,
      refreshSnapshot: true,
    }
  }

  if (payload.type === 'plan_generation_completed') {
    return {
      taskPatch: { status: 'paused_for_review', codex_status: 'waiting_plan_approval' },
      taskRun: waitingPlanApprovalTaskRun(taskRun),
      persist: true,
    }
  }

  if (payload.type === 'quota_exhausted') {
    return {
      taskPatch: {
        status: 'paused_for_review',
        codex_status: 'interrupted',
        notes: payload.reason || activeTask.notes,
      },
      taskRun: quotaBlockedTaskRun(taskRun, payload.reason),
      persist: true,
      closeStream: true,
      refreshSnapshot: true,
    }
  }

  if (RUNNING_EVENT_TYPES.has(payload.type)) {
    return {
      taskPatch: { status: 'running', codex_status: 'running' },
      taskRun: runningTaskRun(taskRun),
      persist: true,
    }
  }

  if (payload.type === 'activity') {
    return {
      taskRun: activityTaskRun(taskRun, payload),
      persist: true,
    }
  }

  return null
}

function completedTaskRun(taskRun) {
  return {
    ...(taskRun || {}),
    progress_percent: 100,
    progress_source: 'realtime',
    progress_unavailable_reason: null,
    progress_status: 'completed',
    current_stage: 'report_generation',
    current_activity: '',
    steps: completeSteps(taskRun?.steps),
    codex: {
      ...(taskRun?.codex || {}),
      status: 'completed',
      progress: {
        ...(taskRun?.codex?.progress || {}),
        status: 'completed',
        current_step: 'completed',
      },
      steps: completeSteps(taskRun?.codex?.steps),
    },
  }
}

function runningTaskRun(taskRun) {
  return {
    ...(taskRun || {}),
    progress_status: 'running',
    progress_unavailable_reason: null,
    open_request_count: 0,
    my_open_request_count: 0,
    steps: clearWaitingSteps(taskRun?.steps),
    codex: {
      ...(taskRun?.codex || {}),
      status: 'running',
      progress: {
        ...(taskRun?.codex?.progress || {}),
        status: 'running',
        current_step: 'running',
      },
      steps: clearWaitingSteps(taskRun?.codex?.steps),
    },
  }
}

function waitingPlanApprovalTaskRun(taskRun) {
  return {
    ...(taskRun || {}),
    progress_status: 'waiting_plan_approval',
    codex: {
      ...(taskRun?.codex || {}),
      status: 'waiting_plan_approval',
      progress: {
        ...(taskRun?.codex?.progress || {}),
        status: 'waiting_plan_approval',
        current_step: 'waiting_plan_approval',
      },
    },
  }
}

function quotaBlockedTaskRun(taskRun, reason) {
  return {
    ...(taskRun || {}),
    progress_status: 'blocked',
    current_activity: reason || taskRun?.current_activity || '',
    codex: {
      ...(taskRun?.codex || {}),
      status: 'interrupted',
    },
  }
}

function activityTaskRun(taskRun, payload) {
  return {
    ...(taskRun || {}),
    current_activity: payload.message || taskRun?.current_activity || '',
    progress_status: payload.status || taskRun?.progress_status || '',
  }
}

function completeSteps(steps) {
  if (!Array.isArray(steps)) return steps
  return steps.map((step) => ({ ...step, status: 'completed' }))
}

function clearWaitingSteps(steps) {
  if (!Array.isArray(steps)) return steps
  return steps.map((step) => (
    step?.status === 'waiting_human' ? { ...step, status: 'running' } : step
  ))
}
