import { STAGE_LABELS, mapStatus, mapTask } from '@/api/mappers'
import { request } from '@/api/request'

function mapHumanRequest(requestRecord, task) {
  const payload = requestRecord?.payload || {}
  const stage = requestRecord?.stage || 'training_validation'
  const details = payload.details || {}
  const parameters = details.parameters || {}
  const taskSpec = {
    target_column: task?.target_column || task?.label_column || '',
    task_type: task?.task_type || task?.problem_type || '',
    metric: task?.metric || task?.last_run?.metric_name || parameters.metric_name || '',
    time_budget_s: parameters.time_limit || '',
  }
  return {
    id: requestRecord?.id,
    status: requestRecord?.status || 'pending',
    stage,
    stage_label: STAGE_LABELS[stage] || stage,
    default_action: payload.suggested_action || 'Confirm and continue',
    summary: payload.summary || '',
    title: payload.title || '',
    task_spec: taskSpec,
    train_plan: { time_budget_s: taskSpec.time_budget_s },
    risk_notes: payload.risk_notes || [],
    parameters,
    ...payload,
  }
}

export async function getHitl(taskId) {
  const snapshot = await request(`/tasks/${taskId}/human-collaboration`)
  const requestRecord = (snapshot.my_requests || snapshot.requests || []).find((item) => ['pending', 'open'].includes(item.status))
    || snapshot.requests?.find((item) => ['pending', 'open'].includes(item.status))
    || snapshot.requests?.[0]
  const task = mapTask(snapshot.task)
  const mappedRequest = mapHumanRequest(requestRecord, task)
  return {
    status: requestRecord?.status || (snapshot.open_request_count ? 'pending' : 'none'),
    request: mappedRequest,
    task_spec: mappedRequest.task_spec,
    train_plan: mappedRequest.train_plan,
    open_request_count: snapshot.open_request_count || 0,
  }
}

export async function submitHitl(taskId, payload) {
  const snapshot = await request(`/tasks/${taskId}/human-collaboration`)
  const requestRecord = (snapshot.my_requests || snapshot.requests || []).find((item) => ['pending', 'open'].includes(item.status))
    || snapshot.requests?.find((item) => ['pending', 'open'].includes(item.status))
  if (!requestRecord?.id) throw new Error('There is no open human confirmation request.')
  const actionMap = { verify: 'approve', retry: 'revise', reject: 'reject' }
  const action = actionMap[payload.action] || payload.action || 'approve'
  const decision = await request(`/tasks/${taskId}/human-requests/${requestRecord.id}/decision`, {
    method: 'POST',
    body: JSON.stringify({
      action,
      decision_summary: payload.action === 'retry' ? 'Applied human adjustments and will continue.' : payload.action === 'reject' ? 'Human rejected continuing the task.' : 'Human confirmed continuing the task.',
      artifact_paths: [],
      resume_task: payload.action !== 'reject',
      details: {
        parameters: payload.adjustments || {},
        source: 'vue_frontend_adapter',
      },
    }),
  })
  const isCodexPlanApproval = requestRecord?.payload?.request_type === 'codex_plan_approval'
  const shouldContinueRun = (
    payload.action !== 'reject'
    && action !== 'reject'
    && decision.open_request_count === 0
    && decision.task?.id
    && (isCodexPlanApproval || !['paused_for_review', 'waiting_human'].includes(decision.task.status))
  )
  if (shouldContinueRun) {
    const runTask = await request(`/tasks/${taskId}/run`, {
      method: 'POST',
      body: JSON.stringify({
        resume_after_human: isCodexPlanApproval ? action === 'approve' : action !== 'revise',
        regenerate_plan: isCodexPlanApproval ? action === 'revise' : false,
        plan_text: isCodexPlanApproval && action === 'approve' ? payload.plan_text || null : null,
      }),
    })
    return {
      status: mapStatus(runTask.status),
      task: mapTask(runTask),
      continued_run: true,
    }
  }
  return { status: mapStatus(decision.task?.status), task: mapTask(decision.task), continued_run: false }
}
