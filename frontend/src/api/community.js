import { groupAssets, mapAsset, truncateText } from '@/api/mappers'
import { request } from '@/api/request'
import { getMe } from '@/api/auth'
import { getTaskDetail, getTaskRuntimeSnapshot } from '@/api/tasks'
import { getModelDisplayName } from '@/utils/modelProfile'

async function createAssetFromCommunity(type, payload) {
  const metadata = {
    ...(payload.metadata || {}),
    prompt_template: payload.prompt_template,
    pipeline_overrides: payload.pipeline_overrides || {},
  }
  const title = truncateText(payload.name || payload.title || `${type} asset`, 200) || `${type} asset`
  const body = {
    asset_type: type,
    title,
    description: truncateText(payload.description, 4000) || null,
    storage_path: truncateText(payload.storage_path || payload.data_path, 4000) || null,
    category: truncateText(payload.task_category || payload.category || type, 120) || type,
    tags: [],
    visibility: payload.visibility || 'private',
    version: truncateText(payload.version || '1.0.0', 80) || '1.0.0',
    source_task_id: truncateText(payload.source_task_id, 120) || null,
    model_card: payload.model_card || null,
    metadata,
    review_status: payload.status || 'pending',
  }
  const result = await request('/assets', { method: 'POST', body: JSON.stringify(body) })
  return mapAsset(result.asset)
}

export async function publishPrompt(taskId, payload = {}) {
  const detail = await getTaskDetail(taskId)
  const task = detail.task || {}
  return createAssetFromCommunity('prompt', {
    name: payload.name || task.display_name || task.name || '任务提示词',
    description: payload.description || task.requirement || task.description || '',
    task_category: payload.task_category || task.task_type || task.problem_type || null,
    source_task_id: taskId,
    metadata: {
      prompt_title: payload.name || task.display_name || task.name || '',
      prompt_description: payload.description || task.requirement || task.description || '',
      target_column: payload.target_column || task.target_column || '',
      task_type: payload.task_category || task.task_type || task.problem_type || '',
      metric: payload.metric || task.metric || '',
    },
  })
}

export async function publishPlan(taskId, payload = {}) {
  const snapshot = await getTaskRuntimeSnapshot(taskId)
  const task = snapshot.task || {}
  const planText = payload.plan_text || snapshot.task_run?.codex?.plan_text || ''
  if (!planText.trim()) throw new Error(`当前任务还没有可发布的 ${getModelDisplayName()} 执行方案。`)
  return createAssetFromCommunity('plan', {
    name: payload.name || `${task.display_name || task.name || '任务'} 执行方案`,
    description: payload.description,
    source_task_id: taskId,
    metadata: {
      plan_text: planText,
      executor_type: 'codex',
      source_task_id: taskId,
      approved_by_user: true,
      task_type: task.task_type || task.problem_type || '',
      target_column: task.target_column || '',
      metric: task.metric || '',
    },
  })
}

export async function getPrompts(includePending = false) {
  const query = new URLSearchParams({ asset_type: 'prompt' })
  if (!includePending) query.set('visibility', 'team')
  const data = await request(`/assets?${query}`)
  return { items: (data.items || []).map(mapAsset) }
}

export async function getPromptDetail(promptId) {
  const data = await getPrompts(true)
  const item = data.items.find((prompt) => prompt.prompt_id === promptId)
  if (!item) throw new Error('Prompt not found.')
  return item
}

export async function getPlans(includePending = false) {
  const query = new URLSearchParams({ asset_type: 'plan' })
  if (!includePending) query.set('visibility', 'team')
  const data = await request(`/assets?${query}`)
  return { items: (data.items || []).map(mapAsset) }
}

export async function getPlansForReview(includePending = true) {
  return getPlans(includePending)
}

export async function getPlanDetail(planId) {
  const data = await getPlans(true)
  const item = data.items.find((plan) => plan.plan_id === planId)
  if (!item) throw new Error('Plan not found.')
  return item
}

export async function forkPlan(planId) {
  const result = await request(`/assets/${planId}/fork`, {
    method: 'POST',
    body: JSON.stringify({ review_status: 'private' }),
  })
  return mapAsset(result.asset)
}

async function reviewAsset(assetId, payload) {
  const reviewStatus = payload.status === 'approved' ? 'published' : (payload.status || payload.review_status || 'published')
  const result = await request(`/assets/${assetId}/review`, {
    method: 'POST',
    body: JSON.stringify({
      review_status: reviewStatus,
      note: payload.review_note || payload.note || '',
      category: payload.task_category || payload.category || null,
      tags: [],
      visibility: ['approved', 'published'].includes(payload.status) || reviewStatus === 'published' ? 'team' : null,
    }),
  })
  return mapAsset(result.asset)
}

export async function reviewPrompt(promptId, payload) {
  return reviewAsset(promptId, payload)
}

export async function reviewPlan(planId, payload) {
  return reviewAsset(planId, payload)
}

export async function deleteCommunityPrompt(promptId) {
  return request(`/assets/${promptId}`, { method: 'DELETE' })
}

export async function deleteCommunityPlan(planId) {
  return request(`/assets/${planId}`, { method: 'DELETE' })
}

export async function getMyAssets() {
  const data = await request('/assets')
  const me = await getMe()
  return groupAssets((data.items || []).filter((asset) => !asset.created_by || asset.created_by === me.user.user_id))
}
