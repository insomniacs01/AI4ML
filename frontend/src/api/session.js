import { supabase, supabaseReady } from '@/lib/supabase'

import { localizeError } from '@/api/errors'

export const ACTIVE_TEAM_KEY = 'ai4ml-active-team-id'
export const MEMBERSHIP_CACHE_KEY = 'ai4ml-membership-cache-v1'
export const DEFAULT_TEAM_NAME = '我的团队'

let cachedSession = null
let cachedUser = null
let cachedMemberships = null
let cachedActiveTeam = null
let cachedMembershipsAt = 0
let pendingSession = null
let pendingMemberships = null

const SESSION_REFRESH_SKEW_SECONDS = 90
const MEMBERSHIP_CACHE_TTL_MS = 10 * 60 * 1000
const MEMBERSHIP_STALE_CACHE_TTL_MS = 24 * 60 * 60 * 1000

export function normalizeRole(role) {
  if (['team_owner', 'admin'].includes(role)) return 'admin'
  if (role === 'developer_user') return 'developer'
  return 'business'
}

export function nativeRole(role) {
  if (role === 'developer') return 'developer_user'
  if (role === 'admin' || role === 'community_admin') return 'admin'
  return 'business_user'
}

export function requireSupabase() {
  if (!supabaseReady || !supabase) throw new Error('Supabase is not configured.')
  return supabase
}

export function getCachedUser() {
  return cachedUser
}

export function getActiveTeamHint() {
  if (cachedActiveTeam?.id) return cachedActiveTeam
  if (typeof localStorage === 'undefined') return null
  const saved = localStorage.getItem(ACTIVE_TEAM_KEY)
  return saved ? { id: saved } : null
}

export function setCachedAuth(session, user = session?.user || null) {
  cachedSession = session || null
  cachedUser = user || cachedSession?.user || null
}

export async function getSession() {
  const client = requireSupabase()
  if (!pendingSession) {
    pendingSession = client.auth.getSession()
      .then(({ data, error }) => {
        if (error) throw error
        setCachedAuth(data.session || null)
        return cachedSession
      })
      .finally(() => {
        pendingSession = null
      })
  }
  return pendingSession
}

function sessionIsFresh(session) {
  if (!session?.access_token) return false
  if (!session.expires_at) return true
  return session.expires_at - Math.floor(Date.now() / 1000) > SESSION_REFRESH_SKEW_SECONDS
}

export async function requireSession(options = {}) {
  const forceRefresh = options.forceRefresh === true
  const session = !forceRefresh && sessionIsFresh(cachedSession) ? cachedSession : await getSession()
  if (!session?.access_token) throw new Error('Please sign in first.')
  cachedUser = session.user
  return session
}

export async function resetAuthCaches(options = {}) {
  cachedSession = null
  cachedUser = null
  cachedMemberships = null
  cachedActiveTeam = null
  cachedMembershipsAt = 0
  pendingSession = null
  pendingMemberships = null
  if (options.clearStoredMemberships !== false) clearStoredMemberships()
}

export async function ensureMemberships(force = false) {
  if (cachedMemberships && !force && Date.now() - cachedMembershipsAt < MEMBERSHIP_CACHE_TTL_MS) return cachedMemberships
  if (!force && !cachedUser?.id) {
    await requireSession()
  }
  if (!force) {
    const stored = readStoredMemberships(cachedUser?.id)
    if (stored) return stored
    const staleStored = readStoredMemberships(cachedUser?.id, { allowStale: true })
    if (staleStored) {
      refreshMembershipsInBackground()
      return staleStored
    }
  }
  if (!force && pendingMemberships) return pendingMemberships

  pendingMemberships = loadMemberships()
    .finally(() => {
      pendingMemberships = null
    })
  return pendingMemberships
}

function refreshMembershipsInBackground() {
  if (pendingMemberships) return
  pendingMemberships = loadMemberships()
    .catch(() => cachedMemberships || [])
    .finally(() => {
      pendingMemberships = null
    })
}

async function loadMemberships() {
  const client = requireSupabase()
  const session = await requireSession()
  const { data: membershipRows, error: membershipError } = await client
    .from('team_members')
    .select('team_id, role, member_status, joined_at')
    .eq('user_id', session.user.id)
    .in('member_status', ['active', 'invited'])
    .order('joined_at', { ascending: true })
  if (membershipError) throw membershipError

  if (!membershipRows?.length) {
    cachedMemberships = []
    cachedActiveTeam = null
    cachedMembershipsAt = Date.now()
    writeStoredMemberships(session.user.id, cachedMemberships)
    return cachedMemberships
  }

  const teamIds = membershipRows.map((row) => row.team_id)
  const { data: teamRows, error: teamRowsError } = await client
    .from('teams')
    .select('id, name, invite_code, created_by, description, status, created_at, updated_at')
    .in('id', teamIds)
  if (teamRowsError) throw teamRowsError

  const teamMap = new Map((teamRows || []).map((team) => [team.id, team]))
  cachedMemberships = membershipRows.map((row) => ({
    id: row.team_id,
    team_id: row.team_id,
    role: row.role,
    role_label: normalizeRole(row.role),
    member_status: row.member_status,
    joined_at: row.joined_at,
    ...(teamMap.get(row.team_id) || {}),
    name: teamMap.get(row.team_id)?.name || row.team_id,
  }))
  cachedMembershipsAt = Date.now()
  writeStoredMemberships(session.user.id, cachedMemberships)
  return cachedMemberships
}

export async function ensureActiveTeam(force = false) {
  const memberships = await ensureMemberships(force)
  if (!memberships.length) throw new Error('The current account has no team. Create or join a team first.')
  const saved = localStorage.getItem(ACTIVE_TEAM_KEY)
  const active = memberships.find((item) => item.id === saved && item.member_status === 'active')
    || memberships.find((item) => item.member_status === 'active')
    || memberships[0]
  cachedActiveTeam = active
  if (active?.id) localStorage.setItem(ACTIVE_TEAM_KEY, active.id)
  return active
}

export async function createTeam(name = DEFAULT_TEAM_NAME) {
  const client = requireSupabase()
  await requireSession()
  const { data, error } = await client.rpc('create_team_with_owner', { team_name: name })
  if (error) throw new Error(localizeError(error.message, 400))
  localStorage.setItem(ACTIVE_TEAM_KEY, data)
  await ensureMemberships(true)
  return { team_id: data }
}

export async function ensureDefaultTeam() {
  const memberships = await ensureMemberships(true)
  if (!memberships.length) return createTeam(DEFAULT_TEAM_NAME)
  return null
}

function readStoredMemberships(userId, options = {}) {
  if (typeof localStorage === 'undefined' || !userId) return null
  try {
    const payload = JSON.parse(localStorage.getItem(MEMBERSHIP_CACHE_KEY) || 'null')
    if (!payload || payload.user_id !== userId) return null
    if (!Array.isArray(payload.memberships)) return null
    const age = Date.now() - Number(payload.cached_at || 0)
    if (age >= MEMBERSHIP_STALE_CACHE_TTL_MS) return null
    if (age >= MEMBERSHIP_CACHE_TTL_MS && options.allowStale !== true) return null
    if (age >= MEMBERSHIP_CACHE_TTL_MS && !payload.memberships.length) return null
    cachedMemberships = payload.memberships
    cachedMembershipsAt = Number(payload.cached_at || Date.now())
    const saved = localStorage.getItem(ACTIVE_TEAM_KEY)
    cachedActiveTeam = cachedMemberships.find((item) => item.id === saved || item.team_id === saved) || null
    return cachedMemberships
  } catch {
    return null
  }
}

function writeStoredMemberships(userId, memberships) {
  if (typeof localStorage === 'undefined' || !userId) return
  localStorage.setItem(MEMBERSHIP_CACHE_KEY, JSON.stringify({
    user_id: userId,
    cached_at: Date.now(),
    memberships,
  }))
}

function clearStoredMemberships() {
  if (typeof localStorage === 'undefined') return
  localStorage.removeItem(MEMBERSHIP_CACHE_KEY)
}
