import { afterEach, describe, expect, it, vi } from 'vitest'
import { ensureMemberships, MEMBERSHIP_CACHE_KEY, resetAuthCaches } from '@/api/session'
import { supabase } from '@/lib/supabase'

const localStorageMock = (() => {
  let store = new Map()
  return {
    getItem: vi.fn((key) => store.get(String(key)) ?? null),
    setItem: vi.fn((key, value) => store.set(String(key), String(value))),
    removeItem: vi.fn((key) => store.delete(String(key))),
    clear: vi.fn(() => {
      store = new Map()
    }),
  }
})()

vi.stubGlobal('localStorage', localStorageMock)

vi.mock('@/lib/supabase', () => ({
  supabaseReady: true,
  supabase: {
    auth: {
      getSession: vi.fn(async () => ({
        data: { session: { access_token: 'token', user: { id: 'user-1', email: 'user@example.com' } } },
        error: null,
      })),
    },
    from: vi.fn((table) => supabaseTableMock(table)),
  },
}))

afterEach(async () => {
  await resetAuthCaches()
  localStorage.clear()
  vi.clearAllMocks()
})

describe('session cache', () => {
  it('coalesces concurrent membership loads', async () => {
    const [first, second, third] = await Promise.all([
      ensureMemberships(),
      ensureMemberships(),
      ensureMemberships(),
    ])

    expect(first).toBe(second)
    expect(second).toBe(third)
    expect(first).toHaveLength(1)
    expect(supabase.auth.getSession).toHaveBeenCalledTimes(1)
    expect(supabase.from).toHaveBeenCalledTimes(2)
    expect(supabase.from.mock.calls.map(([table]) => table)).toEqual(['team_members', 'teams'])

    await ensureMemberships()

    expect(supabase.from).toHaveBeenCalledTimes(2)
  })

  it('restores fresh memberships from local storage without Supabase table reads', async () => {
    localStorage.setItem(MEMBERSHIP_CACHE_KEY, JSON.stringify({
      user_id: 'user-1',
      cached_at: Date.now(),
      memberships: [{
        id: 'team-1',
        team_id: 'team-1',
        role: 'admin',
        role_label: 'admin',
        member_status: 'active',
        name: 'Team 1',
      }],
    }))

    const memberships = await ensureMemberships()

    expect(memberships).toHaveLength(1)
    expect(memberships[0].id).toBe('team-1')
    expect(supabase.auth.getSession).toHaveBeenCalledTimes(1)
    expect(supabase.from).not.toHaveBeenCalled()
  })

  it('keeps nine-minute memberships in local storage cache', async () => {
    localStorage.setItem(MEMBERSHIP_CACHE_KEY, JSON.stringify({
      user_id: 'user-1',
      cached_at: Date.now() - 9 * 60 * 1000,
      memberships: [{
        id: 'team-1',
        team_id: 'team-1',
        role: 'admin',
        role_label: 'admin',
        member_status: 'active',
        name: 'Team 1',
      }],
    }))

    const memberships = await ensureMemberships()

    expect(memberships).toHaveLength(1)
    expect(supabase.from).not.toHaveBeenCalled()
  })

  it('uses stale memberships after ten minutes and refreshes them in the background', async () => {
    localStorage.setItem(MEMBERSHIP_CACHE_KEY, JSON.stringify({
      user_id: 'user-1',
      cached_at: Date.now() - 11 * 60 * 1000,
      memberships: [{
        id: 'stale-team',
        team_id: 'stale-team',
        role: 'admin',
        role_label: 'admin',
        member_status: 'active',
        name: 'Stale Team',
      }],
    }))

    const memberships = await ensureMemberships()

    expect(memberships).toHaveLength(1)
    expect(memberships[0].id).toBe('stale-team')

    await Promise.resolve()
    await Promise.resolve()

    expect(supabase.from).toHaveBeenCalledTimes(2)
  })

  it('reloads memberships when local storage cache is older than one day', async () => {
    localStorage.setItem(MEMBERSHIP_CACHE_KEY, JSON.stringify({
      user_id: 'user-1',
      cached_at: Date.now() - 25 * 60 * 60 * 1000,
      memberships: [{
        id: 'expired-team',
        team_id: 'expired-team',
        role: 'admin',
        role_label: 'admin',
        member_status: 'active',
        name: 'Expired Team',
      }],
    }))

    const memberships = await ensureMemberships()

    expect(memberships).toHaveLength(1)
    expect(memberships[0].id).toBe('team-1')
    expect(supabase.from).toHaveBeenCalledTimes(2)
  })

  it('can reset in-memory auth state while preserving stored memberships', async () => {
    localStorage.setItem(MEMBERSHIP_CACHE_KEY, JSON.stringify({
      user_id: 'user-1',
      cached_at: Date.now(),
      memberships: [{ id: 'team-1', team_id: 'team-1', role: 'admin', member_status: 'active' }],
    }))

    await resetAuthCaches({ clearStoredMemberships: false })

    expect(localStorage.getItem(MEMBERSHIP_CACHE_KEY)).toContain('team-1')
  })

  it('clears stored memberships by default when resetting auth state', async () => {
    localStorage.setItem(MEMBERSHIP_CACHE_KEY, JSON.stringify({
      user_id: 'user-1',
      cached_at: Date.now(),
      memberships: [{ id: 'team-1', team_id: 'team-1', role: 'admin', member_status: 'active' }],
    }))

    await resetAuthCaches()

    expect(localStorage.getItem(MEMBERSHIP_CACHE_KEY)).toBeNull()
  })
})

function supabaseTableMock(table) {
  const query = {
    select: vi.fn(() => query),
    eq: vi.fn(() => query),
    in: vi.fn(() => query),
    order: vi.fn(async () => {
      await Promise.resolve()
      if (table === 'team_members') {
        return {
          data: [{ team_id: 'team-1', role: 'admin', member_status: 'active', joined_at: '2026-05-19T00:00:00Z' }],
          error: null,
        }
      }
      return { data: [], error: null }
    }),
  }
  if (table === 'teams') {
    query.in = vi.fn(async () => {
      await Promise.resolve()
      return {
        data: [{ id: 'team-1', name: 'Team 1', status: 'active' }],
        error: null,
      }
    })
  }
  return query
}
