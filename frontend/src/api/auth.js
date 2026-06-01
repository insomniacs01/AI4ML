import { localizeError } from '@/api/errors'
import { optionalRequest } from '@/api/request'
import {
  DEFAULT_TEAM_NAME,
  createTeam,
  ensureActiveTeam,
  ensureMemberships,
  normalizeRole,
  requireSession,
  requireSupabase,
  resetAuthCaches,
  setCachedAuth,
} from '@/api/session'
import { warmupTaskCacheSoon } from '@/api/taskCache'

async function ensureTeamMembership() {
  const memberships = await ensureMemberships(true)
  if (!memberships.length) await createTeam(DEFAULT_TEAM_NAME)
}

export async function login(payload) {
  const client = requireSupabase()
  const email = String(payload.email || payload.user_id || '').trim()
  const password = String(payload.password || '')
  const { data, error } = await client.auth.signInWithPassword({ email, password })
  if (error) throw new Error(localizeError(error.message, 401))
  await resetAuthCaches()
  setCachedAuth(data.session, data.user)
  await ensureTeamMembership()
  const me = await getMe()
  warmupTaskCacheSoon()
  return me
}

export async function register(payload) {
  const client = requireSupabase()
  const email = String(payload.email || payload.user_id || '').trim()
  const password = String(payload.password || '')
  const displayName = String(payload.display_name || payload.displayName || '').trim()
  const { data, error } = await client.auth.signUp({
    email,
    password,
    options: { data: { display_name: displayName } },
  })
  if (error) throw new Error(localizeError(error.message, 400))
  await resetAuthCaches()
  setCachedAuth(data.session || null, data.user || null)
  if (data.session?.access_token) {
    await ensureTeamMembership()
    warmupTaskCacheSoon()
  }
  return { user: data.user }
}

export async function changePassword(payload) {
  const client = requireSupabase()
  const { error } = await client.auth.updateUser({ password: payload.new_password })
  if (error) throw new Error(localizeError(error.message, 400))
  return { ok: true }
}

export async function logout() {
  const client = requireSupabase()
  await client.auth.signOut()
  await resetAuthCaches()
  return { ok: true }
}

export async function getMe() {
  const session = await requireSession()
  let memberships = await ensureMemberships()
  if (!memberships.length) {
    await createTeam(DEFAULT_TEAM_NAME)
    memberships = await ensureMemberships(true)
  }
  const activeTeam = memberships.length ? await ensureActiveTeam() : null
  if (activeTeam?.id) warmupTaskCacheSoon()
  const metadata = session.user.user_metadata || {}
  return {
    user: {
      user_id: session.user.id,
      email: session.user.email,
      display_name: metadata.display_name || session.user.email || session.user.id,
      role: normalizeRole(activeTeam?.role),
      native_role: activeTeam?.role || '',
      active_team_id: activeTeam?.id || '',
      active_team_name: activeTeam?.name || '',
      memberships,
    },
  }
}

export async function getCurrentUser() {
  return getMe()
}

export async function getProfile() {
  const [me, quota] = await Promise.all([
    getMe(),
    optionalRequest('/quotas', {}, { items: [] }),
  ])
  const mine = quota?.items?.find((item) => item.user_id === me.user.user_id) || {}
  return {
    ...me.user,
    token_quota: mine.token_quota || 0,
    token_used: mine.token_used || 0,
    token_remaining: mine.token_remaining ?? Math.max(0, Number(mine.token_quota || 0) - Number(mine.token_used || 0)),
    quota_status: mine.status || 'active',
  }
}

export async function updateProfile(payload) {
  const client = requireSupabase()
  const { data, error } = await client.auth.updateUser({ data: { display_name: payload.display_name } })
  if (error) throw new Error(localizeError(error.message, 400))
  setCachedAuth(null, data.user)
  return getProfile()
}
