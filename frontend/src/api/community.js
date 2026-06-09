import { groupAssets, mapAsset, truncateText } from '@/api/mappers'
import { request } from '@/api/request'
import { getMe } from '@/api/auth'
import { getActiveTeamHint } from '@/api/session'
import { getTaskDetail, getTaskRuntimeSnapshot } from '@/api/tasks'
import { getModelDisplayName } from '@/utils/modelProfile'

const ASSET_CACHE_PREFIX = 'ai4ml-community-assets-cache-v2'
const ASSET_CACHE_TTL_MS = 10 * 60 * 1000
const ASSET_STALE_CACHE_TTL_MS = 24 * 60 * 60 * 1000
const pendingAssetRefreshes = new Map()
let assetCacheGeneration = 0
let lastAssetCacheWarmupAt = 0

async function listAssets({ assetType = null, includePending = false, forceRefresh = false } = {}) {
  const cacheKey = assetListCacheKey({ assetType, includePending })
  if (!forceRefresh) {
    const cached = readAssetListCache(cacheKey)
    if (cached) return cached
    const staleCached = readAssetListCache(cacheKey, { allowStale: true })
    if (staleCached) {
      refreshAssetListInBackground(cacheKey, { assetType, includePending })
      return staleCached
    }
  }
  return fetchAssetList(cacheKey, { assetType, includePending })
}

async function fetchAssetList(cacheKey, { assetType = null, includePending = false } = {}) {
  const generation = assetCacheGeneration
  const query = new URLSearchParams()
  if (assetType) query.set('asset_type', assetType)
  if (!includePending) query.set('visibility', 'team')
  const suffix = query.toString()
  const data = await request(`/assets${suffix ? `?${suffix}` : ''}`)
  const items = data.items || []
  if (generation === assetCacheGeneration) writeAssetListCache(cacheKey, items)
  return items
}

function refreshAssetListInBackground(cacheKey, options) {
  if (pendingAssetRefreshes.has(cacheKey)) return
  const refresh = fetchAssetList(cacheKey, options)
    .catch(() => null)
    .finally(() => {
      pendingAssetRefreshes.delete(cacheKey)
    })
  pendingAssetRefreshes.set(cacheKey, refresh)
}

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
  clearAssetListCaches()
  return mapAsset(result.asset)
}

export async function publishPrompt(taskId, payload = {}) {
  if (hasDirectPublishPayload(payload)) {
    return createPromptAsset(taskId, {
      name: payload.name || '任务提示词',
      description: payload.description || '',
      task_category: payload.task_category || null,
      target_column: payload.target_column || '',
      metric: payload.metric || '',
    })
  }
  const detail = await getTaskDetail(taskId)
  const task = detail.task || {}
  return createPromptAsset(taskId, {
    name: payload.name || task.display_name || task.name || '任务提示词',
    description: payload.description || task.requirement || task.description || '',
    task_category: payload.task_category || task.task_type || task.problem_type || null,
    target_column: payload.target_column || task.target_column || '',
    metric: payload.metric || task.metric || '',
  })
}

export async function publishPlan(taskId, payload = {}) {
  const providedPlanText = String(payload.plan_text || '')
  if (providedPlanText.trim()) {
    return createPlanAsset(taskId, {
      name: payload.name || '任务执行方案',
      description: payload.description,
      plan_text: providedPlanText,
      task_category: payload.task_category || '',
      target_column: payload.target_column || '',
      metric: payload.metric || '',
    })
  }
  const snapshot = await getTaskRuntimeSnapshot(taskId, { sync: false })
  const task = snapshot.task || {}
  const planText = snapshot.task_run?.codex?.plan_text || ''
  if (!planText.trim()) throw new Error(`当前任务还没有可发布的 ${getModelDisplayName()} 执行方案。`)
  return createPlanAsset(taskId, {
    name: payload.name || `${task.display_name || task.name || '任务'} 执行方案`,
    description: payload.description,
    plan_text: planText,
    task_category: task.task_type || task.problem_type || '',
    target_column: task.target_column || '',
    metric: task.metric || '',
  })
}

function hasDirectPublishPayload(payload) {
  return Object.prototype.hasOwnProperty.call(payload, 'name')
    && Object.prototype.hasOwnProperty.call(payload, 'description')
}

function createPromptAsset(taskId, payload) {
  return createAssetFromCommunity('prompt', {
    name: payload.name,
    description: payload.description,
    task_category: payload.task_category,
    source_task_id: taskId,
    metadata: {
      prompt_title: payload.name || '',
      prompt_description: payload.description || '',
      target_column: payload.target_column || '',
      task_type: payload.task_category || '',
      metric: payload.metric || '',
    },
  })
}

function createPlanAsset(taskId, payload) {
  return createAssetFromCommunity('plan', {
    name: payload.name,
    description: payload.description,
    source_task_id: taskId,
    metadata: {
      plan_text: payload.plan_text,
      executor_type: 'codex',
      source_task_id: taskId,
      approved_by_user: true,
      task_type: payload.task_category || '',
      target_column: payload.target_column || '',
      metric: payload.metric || '',
    },
  })
}

export async function getPrompts(includePending = false) {
  return { items: (await listAssets({ assetType: 'prompt', includePending })).map(mapAsset) }
}

export async function getPromptDetail(promptId) {
  const data = await request(`/assets/${encodeURIComponent(promptId)}`)
  const item = mapAsset(data.asset)
  if (!item || item.asset_type !== 'prompt') throw new Error('Prompt not found.')
  return item
}

export async function getPlans(includePending = false) {
  return { items: (await listAssets({ assetType: 'plan', includePending })).map(mapAsset) }
}

export async function getPlansForReview(includePending = true) {
  return getPlans(includePending)
}

export async function getPlanDetail(planId) {
  const data = await request(`/assets/${encodeURIComponent(planId)}`)
  const item = mapAsset(data.asset)
  if (!item || item.asset_type !== 'plan') throw new Error('Plan not found.')
  return item
}

export async function getCommunityAssets(includePending = false) {
  return groupAssets(await listAssets({ includePending }))
}

export async function warmupCommunityAssetCaches({ includePending = false } = {}) {
  await listAssets({ includePending: false })
  if (includePending) await listAssets({ includePending: true })
}

export function warmupCommunityAssetCachesSoon(options = {}) {
  const now = Date.now()
  if (now - lastAssetCacheWarmupAt < 30_000) return
  lastAssetCacheWarmupAt = now
  const delayMs = Number(options.delayMs || 0)
  globalThis.setTimeout(() => {
    warmupCommunityAssetCaches(options).catch(() => {})
  }, delayMs)
}

export async function forkPlan(planId) {
  const result = await request(`/assets/${planId}/fork`, {
    method: 'POST',
    body: JSON.stringify({ review_status: 'private' }),
  })
  clearAssetListCaches()
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
  clearAssetListCaches()
  return mapAsset(result.asset)
}

export async function reviewPrompt(promptId, payload) {
  return reviewAsset(promptId, payload)
}

export async function reviewPlan(planId, payload) {
  return reviewAsset(planId, payload)
}

export async function deleteCommunityPrompt(promptId) {
  const result = await request(`/assets/${promptId}`, { method: 'DELETE' })
  clearAssetListCaches()
  return result
}

export async function deleteCommunityPlan(planId) {
  const result = await request(`/assets/${planId}`, { method: 'DELETE' })
  clearAssetListCaches()
  return result
}

export async function getMyAssets() {
  const items = await listAssets({ includePending: true })
  const me = await getMe()
  return groupAssets(items.filter((asset) => !asset.created_by || asset.created_by === me.user.user_id))
}

function assetListCacheKey({ assetType = null, includePending = false } = {}) {
  const teamId = getActiveTeamHint()?.id || 'default'
  return [
    ASSET_CACHE_PREFIX,
    teamId,
    includePending ? 'all' : 'team',
    assetType || 'all',
  ].join(':')
}

function readAssetListCache(cacheKey, options = {}) {
  if (typeof localStorage === 'undefined') return null
  try {
    const payload = JSON.parse(localStorage.getItem(cacheKey) || 'null')
    if (!payload || !Array.isArray(payload.items)) return null
    const age = Date.now() - Number(payload.cached_at || 0)
    if (age >= ASSET_STALE_CACHE_TTL_MS) return null
    if (age >= ASSET_CACHE_TTL_MS && options.allowStale !== true) return null
    return payload.items
  } catch {
    return null
  }
}

function writeAssetListCache(cacheKey, items) {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(cacheKey, JSON.stringify({
    cached_at: Date.now(),
    items,
  }))
}

function clearAssetListCaches() {
  assetCacheGeneration += 1
  pendingAssetRefreshes.clear()
  if (typeof localStorage === 'undefined') return
  const keys = []
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index)
    if (key && key.startsWith(`${ASSET_CACHE_PREFIX}:`)) keys.push(key)
  }
  keys.forEach((key) => localStorage.removeItem(key))
}
