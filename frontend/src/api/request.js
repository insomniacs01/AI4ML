import { localizeError } from '@/api/errors'
import { ensureActiveTeam, getActiveTeamHint, requireSession, resetAuthCaches } from '@/api/session'

export const API_ROOT = (import.meta.env.VITE_API_ROOT || '/api').replace(/\/+$/, '')

export function teamPath(teamId, path) {
  return `${API_ROOT}/teams/${encodeURIComponent(teamId)}${path.startsWith('/') ? path : `/${path}`}`
}

export async function request(path, options = {}) {
  const { teamScoped = true, teamId = null, allowMissingTeam = false, headers, ...fetchOptions } = options
  const session = await requireSession()
  let url = `${API_ROOT}${path}`
  let activeTeam = null
  if (teamScoped) {
    activeTeam = teamId ? { id: teamId } : getActiveTeamHint()
    try {
      if (!activeTeam?.id) activeTeam = await ensureActiveTeam()
    } catch (err) {
      if (!allowMissingTeam) throw err
    }
    if (activeTeam?.id) url = teamPath(activeTeam.id, path)
  }

  const nextHeaders = new Headers(headers || {})
  nextHeaders.set('Authorization', `Bearer ${session.access_token}`)
  if (activeTeam?.id) nextHeaders.set('X-Team-Id', activeTeam.id)
  if (!(fetchOptions.body instanceof FormData) && fetchOptions.body != null && !nextHeaders.has('Content-Type')) {
    nextHeaders.set('Content-Type', 'application/json')
  }

  const resp = await fetch(url, { ...fetchOptions, headers: nextHeaders })
  const contentType = resp.headers.get('content-type') || ''
  const data = contentType.includes('application/json') ? await resp.json().catch(() => ({})) : await resp.text()
  if (!resp.ok) {
    const detail = typeof data === 'object' ? data.msg || data.detail || JSON.stringify(data) : data
    if (resp.status === 401 && String(detail || '').toLowerCase().includes('supabase rejected')) {
      await resetAuthCaches()
    }
    throw new Error(localizeError(detail, resp.status))
  }
  return data
}

export async function optionalRequest(path, options = {}, fallback = null) {
  try {
    return await request(path, options)
  } catch {
    return fallback
  }
}
