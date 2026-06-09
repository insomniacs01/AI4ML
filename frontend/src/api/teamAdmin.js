import { optionalRequest, request } from '@/api/request'
import { getActiveTeamHint, nativeRole, normalizeRole } from '@/api/session'

const TEAM_ADMIN_CACHE_PREFIX = 'ai4ml-team-admin-cache-v1'
const TEAM_ADMIN_CACHE_TTL_MS = 10 * 60 * 1000
const TEAM_ADMIN_CACHE_SCOPES = ['settings', 'members', 'quotas', 'platform-limits']
const pendingTeamAdminReads = new Map()
let teamAdminCacheGeneration = 0
let lastTeamAdminWarmupAt = 0

export async function getUsers(options = {}) {
  const memberData = options.memberData || await getTeamMembers()
  const quotaData = options.includeQuotas === false
    ? { items: [], loaded: false }
    : { ...(await readThroughTeamAdminCache('quotas', () => optionalRequest('/quotas', {}, { items: [] }))), loaded: true }
  return buildUsersFromMembers(memberData, quotaData.items || [], quotaData.loaded)
}

function buildUsersFromMembers(memberData, quotaItems = [], quotaLoaded = true) {
  const quotaByUser = new Map(
    quotaItems
      .filter((item) => item.scope_type === 'member' && (item.user_id || item.scope_key))
      .map((item) => [item.user_id || item.scope_key, item]),
  )
  return {
    items: (memberData.items || []).map((member) => {
      const quota = quotaByUser.get(member.user_id) || {}
      const displayName = member.profile?.display_name || member.display_name || member.profile?.email || member.email || member.user_id
      const email = member.profile?.email || member.email || ''
      return {
        user_id: member.user_id,
        display_name: displayName,
        email,
        original_display_name: displayName,
        role: normalizeRole(member.role),
        original_role: normalizeRole(member.role),
        native_role: member.role,
        original_native_role: member.role,
        member_status: member.member_status || 'active',
        token_quota: Number(quota.token_quota || 0),
        original_token_quota: Number(quota.token_quota || 0),
        token_used: Number(quota.token_used || 0),
        token_remaining: quota.token_remaining === null || quota.token_remaining === undefined
          ? Math.max(0, Number(quota.token_quota || 0) - Number(quota.token_used || 0))
          : Number(quota.token_remaining),
        quota_status: quota.status || 'active',
        original_quota_status: quota.status || 'active',
        warning_threshold: quota.warning_threshold || 0,
        original_warning_threshold: quota.warning_threshold || 0,
        is_active: member.member_status === 'active' && quota.status !== 'frozen',
        original_is_active: member.member_status === 'active' && quota.status !== 'frozen',
        quota_loaded: quotaLoaded,
      }
    }),
  }
}

export async function getTeamSettings() {
  return readThroughTeamAdminCache('settings', async () => {
    const data = await request('/settings')
    return data.team || null
  })
}

export async function getTeamMembers() {
  return readThroughTeamAdminCache('members', async () => {
    const data = await request('/members')
    return {
      team_id: data.team_id,
      items: (data.items || []).map((member) => ({
        user_id: member.user_id,
        display_name: member.profile?.display_name || member.profile?.email || member.user_id,
        email: member.profile?.email || '',
        role: member.role || 'member',
        role_label: normalizeRole(member.role),
        member_status: member.member_status || 'active',
        joined_at: member.joined_at || null,
        invited_by: member.invited_by || '',
      })),
    }
  })
}

export async function createTeamInvite(payload = {}) {
  return request('/members/invite', {
    method: 'POST',
    body: JSON.stringify({
      email: payload.email || null,
      note: payload.note || null,
    }),
  })
}

export async function updateTeamMemberRole(userId, role) {
  const result = await request(`/members/${userId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  })
  clearTeamAdminCaches(['members', 'quotas'])
  return result.member
}

export async function updateTeamMemberStatus(userId, memberStatus) {
  const result = await request(`/members/${userId}/status`, {
    method: 'PATCH',
    body: JSON.stringify({ member_status: memberStatus }),
  })
  clearTeamAdminCaches(['members', 'quotas'])
  return result.member
}

export async function updateUser(userId, payload) {
  const body = {}
  if (
    Object.prototype.hasOwnProperty.call(payload, 'display_name')
    && String(payload.display_name || '').trim() !== String(payload.original_display_name || '').trim()
  ) {
    body.display_name = String(payload.display_name || '').trim()
  }
  const nextRole = nativeRole(payload.role)
  const originalNativeRole = payload.original_native_role || ''
  if (!(originalNativeRole === 'team_owner' && nextRole === 'admin') && nextRole !== originalNativeRole) {
    body.role = nextRole
  }
  const nextActive = Boolean(payload.is_active)
  if (nextActive !== Boolean(payload.original_is_active)) {
    body.member_status = nextActive ? 'active' : 'frozen'
    body.quota_status = nextActive ? 'active' : 'frozen'
  } else if (nextActive && payload.original_quota_status && payload.original_quota_status !== 'active') {
    body.quota_status = 'active'
  }
  const nextTokenQuota = Number(payload.token_quota || 0)
  if (nextTokenQuota !== Number(payload.original_token_quota || 0)) {
    body.token_quota = nextTokenQuota
    if (
      !body.quota_status
      && payload.original_quota_status === 'exhausted'
      && nextTokenQuota > Number(payload.token_used || 0)
    ) {
      body.quota_status = 'active'
    }
  }
  const nextWarningThreshold = Number(payload.warning_threshold || 0)
  if (nextWarningThreshold !== Number(payload.original_warning_threshold || 0)) {
    body.warning_threshold = nextWarningThreshold
  }
  const result = await request(`/admin/users/${userId}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
  clearTeamAdminCaches(['members', 'quotas'])
  return result
}

export async function resetUserPassword(userId, password) {
  return request(`/admin/users/${userId}/reset-password`, {
    method: 'POST',
    body: JSON.stringify({ password }),
  })
}

export async function getPlatformLimits() {
  return readThroughTeamAdminCache('platform-limits', () => request('/admin/platform-limits'))
}

export async function warmupTeamAdminCaches({ includeSystemAdmin = false } = {}) {
  const warmups = [getTeamSettings(), getTeamMembers()]
  if (includeSystemAdmin) warmups.push(getPlatformLimits())
  await Promise.all(warmups)
}

export function warmupTeamAdminCachesSoon(options = {}) {
  const now = Date.now()
  if (now - lastTeamAdminWarmupAt < 30_000) return
  lastTeamAdminWarmupAt = now
  const delayMs = Number(options.delayMs || 0)
  globalThis.setTimeout(() => {
    warmupTeamAdminCaches(options).catch(() => {})
  }, delayMs)
}

export async function updatePlatformLimits(payload) {
  const result = await request('/admin/platform-limits', { method: 'PUT', body: JSON.stringify(payload) })
  clearTeamAdminCaches(['platform-limits'])
  writeTeamAdminCache('platform-limits', result)
  return result
}

async function readThroughTeamAdminCache(scope, loader) {
  const cached = readTeamAdminCache(scope)
  if (cached) return cached
  if (pendingTeamAdminReads.has(scope)) return pendingTeamAdminReads.get(scope)
  const generation = teamAdminCacheGeneration
  const pending = loader()
    .then((value) => {
      if (generation === teamAdminCacheGeneration) writeTeamAdminCache(scope, value)
      return value
    })
    .finally(() => {
      pendingTeamAdminReads.delete(scope)
    })
  pendingTeamAdminReads.set(scope, pending)
  return pending
}

function teamAdminCacheKey(scope) {
  const teamId = getActiveTeamHint()?.id || 'default'
  return `${TEAM_ADMIN_CACHE_PREFIX}:${teamId}:${scope}`
}

function readTeamAdminCache(scope) {
  if (typeof localStorage === 'undefined') return null
  try {
    const payload = JSON.parse(localStorage.getItem(teamAdminCacheKey(scope)) || 'null')
    if (!payload || !Object.prototype.hasOwnProperty.call(payload, 'value')) return null
    if (Date.now() - Number(payload.cached_at || 0) >= TEAM_ADMIN_CACHE_TTL_MS) return null
    return payload.value
  } catch {
    return null
  }
}

function writeTeamAdminCache(scope, value) {
  if (typeof localStorage === 'undefined') return
  localStorage.setItem(teamAdminCacheKey(scope), JSON.stringify({
    cached_at: Date.now(),
    value,
  }))
}

function clearTeamAdminCaches(scopes = TEAM_ADMIN_CACHE_SCOPES) {
  teamAdminCacheGeneration += 1
  scopes.forEach((scope) => pendingTeamAdminReads.delete(scope))
  if (typeof localStorage === 'undefined') return
  if (typeof localStorage.length !== 'number' || typeof localStorage.key !== 'function') {
    scopes.forEach((scope) => localStorage.removeItem(teamAdminCacheKey(scope)))
    return
  }
  const keys = []
  for (let index = 0; index < localStorage.length; index += 1) {
    const key = localStorage.key(index)
    if (!key || !key.startsWith(`${TEAM_ADMIN_CACHE_PREFIX}:`)) continue
    if (scopes.some((scope) => key.endsWith(`:${scope}`))) keys.push(key)
  }
  keys.forEach((key) => localStorage.removeItem(key))
}
