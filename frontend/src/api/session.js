import { supabase, supabaseReady } from '@/lib/supabase'

import { localizeError } from '@/api/errors'

export const ACTIVE_TEAM_KEY = 'ai4ml-active-team-id'
export const DEFAULT_TEAM_NAME = '我的团队'

let cachedSession = null
let cachedUser = null
let cachedMemberships = null
let cachedActiveTeam = null
let cachedMembershipsAt = 0

const SESSION_REFRESH_SKEW_SECONDS = 90
const MEMBERSHIP_CACHE_TTL_MS = 2 * 60 * 1000

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
  const { data, error } = await client.auth.getSession()
  if (error) throw error
  setCachedAuth(data.session || null)
  return cachedSession
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

export async function resetAuthCaches() {
  cachedSession = null
  cachedUser = null
  cachedMemberships = null
  cachedActiveTeam = null
  cachedMembershipsAt = 0
}

export async function ensureMemberships(force = false) {
  const client = requireSupabase()
  const session = await requireSession()
  if (cachedMemberships && !force && Date.now() - cachedMembershipsAt < MEMBERSHIP_CACHE_TTL_MS) return cachedMemberships

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
