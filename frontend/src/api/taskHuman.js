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
  const snapshot = await request(`/tasks/${taskId}/human-collaboration?sync=true`)
  const requestRecord = (snapshot.my_requests || snapshot.requests || []).find((item) => ['pending', 'open'].includes(item.status))
    || snapshot.requests?.find((item) => ['pending', 'open'].includes(item.status))
  const task = mapTask(snapshot.task)
  const mappedRequest = requestRecord ? mapHumanRequest(requestRecord, task) : null
  return {
    status: requestRecord?.status || (snapshot.open_request_count ? 'pending' : 'none'),
    request: mappedRequest,
    task_spec: mappedRequest?.task_spec || {
      target_column: task?.target_column || task?.label_column || '',
      task_type: task?.task_type || task?.problem_type || '',
      metric: task?.metric || task?.last_run?.metric_name || '',
      time_budget_s: '',
    },
    train_plan: mappedRequest?.train_plan || { time_budget_s: '' },
    open_request_count: snapshot.open_request_count || 0,
  }
}

export async function submitHitl(taskId, payload) {
  const snapshot = await request(`/tasks/${taskId}/human-collaboration?sync=true`)
  const requestRecord = (snapshot.my_requests || snapshot.requests || []).find((item) => ['pending', 'open'].includes(item.status))
    || snapshot.requests?.find((item) => ['pending', 'open'].includes(item.status))
  if (!requestRecord?.id) throw new Error('There is no open human confirmation request.')
  const actionMap = {
    verify: 'approve',
    retry: 'revise',
    reject: 'reject',
    continue_improvement: 'approve',
    stop_and_report: 'skip',
  }
  const action = actionMap[payload.action] || payload.action || 'approve'
  const improvementDecision = ['continue_improvement', 'stop_and_report'].includes(payload.action) ? payload.action : null
  const decision = await request(`/tasks/${taskId}/human-requests/${requestRecord.id}/decision`, {
    method: 'POST',
    body: JSON.stringify({
      action,
      decision_summary: decisionSummaryForAction(payload.action),
      artifact_paths: [],
      resume_task: payload.action !== 'reject',
      details: {
        parameters: payload.adjustments || {},
        improvement_decision: improvementDecision,
        source: 'vue_frontend_adapter',
      },
    }),
  })
  const isCodexPlanApproval = requestRecord?.payload?.request_type === 'codex_plan_approval'
  const isCodexImprovementReview = requestRecord?.payload?.request_type === 'codex_improvement_review'
  const shouldContinueRun = (
    payload.action !== 'reject'
    && action !== 'reject'
    && decision.open_request_count === 0
    && decision.task?.id
    && (isCodexPlanApproval || isCodexImprovementReview || !['paused_for_review', 'waiting_human'].includes(decision.task.status))
  )
  if (shouldContinueRun) {
    const runTask = await request(`/tasks/${taskId}/run?async_start=true`, {
      method: 'POST',
      body: JSON.stringify({
        resume_after_human: isCodexImprovementReview ? false : isCodexPlanApproval ? action === 'approve' : action !== 'revise',
        resume_interrupted: isCodexImprovementReview,
        regenerate_plan: isCodexPlanApproval ? action === 'revise' : false,
        improvement_decision: isCodexImprovementReview ? improvementDecision : null,
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

function decisionSummaryForAction(action) {
  if (action === 'retry') return 'Applied human adjustments and will continue.'
  if (action === 'reject') return 'Human rejected continuing the task.'
  if (action === 'continue_improvement') return 'Human confirmed continuing the improvement plan.'
  if (action === 'stop_and_report') return 'Human chose to stop further improvement and generate the report.'
  return 'Human confirmed continuing the task.'
}
