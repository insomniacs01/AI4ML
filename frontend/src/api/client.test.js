import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createTask,
  getActiveTask,
  getCommunityAssets,
  getCodexPlan,
  getDelivery,
  getMetrics,
  getMyTasks,
  getNotifications,
  getPlanDetail,
  getProfile,
  getProfileBase,
  getTasks,
  getTaskRuntimeSnapshot,
  getOperationCode,
  getTeamMembers,
  getTeamSettings,
  login,
  register,
  getWorkspaceTasks,
  getUnreadNotificationCount,
  getUsers,
  markAllNotificationsRead,
  predictPublicDemo,
  publishPlan,
  publishPrompt,
  rerunTask,
  submitHitl,
  updateOperationCode,
  updateUser,
  updateModelConfig,
  warmupCommunityAssetCaches,
  warmupNotifications,
  warmupProfileQuota,
  warmupTeamAdminCaches,
} from './client'
import { supabase } from '@/lib/supabase'
import { MEMBERSHIP_CACHE_KEY } from '@/api/session'

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
      signInWithPassword: vi.fn(async () => ({
        data: {
          session: { access_token: 'token', user: { id: 'user-1', email: 'user@example.com' } },
          user: { id: 'user-1', email: 'user@example.com' },
        },
        error: null,
      })),
      signUp: vi.fn(async ({ email }) => ({
        data: {
          session: { access_token: 'token', user: { id: 'user-1', email } },
          user: { id: 'user-1', email },
        },
        error: null,
      })),
    },
    from: vi.fn((table) => supabaseTableMock(table)),
  },
}))

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('api client compatibility helpers', () => {
  it('fails explicitly when public demo prediction has no backend implementation', async () => {
    await expect(predictPublicDemo('demo_1', [{ age: 20 }])).rejects.toThrow('尚未接入后端预测接口')
  })

  it('keeps login on the auth fast path and refreshes team membership later', async () => {
    vi.useFakeTimers()
    try {
      supabase.from.mockClear()
      supabase.auth.signInWithPassword.mockClear()

      const result = await login({
        email: 'user@example.com',
        password: '123456',
      })

      expect(result.user.user_id).toBe('user-1')
      expect(supabase.auth.signInWithPassword).toHaveBeenCalledTimes(1)
      expect(supabase.from).not.toHaveBeenCalled()

      await vi.runOnlyPendingTimersAsync()

      expect(supabase.from).toHaveBeenCalled()
    } finally {
      vi.clearAllTimers()
      vi.useRealTimers()
    }
  })

  it('returns the registration session so callers can skip duplicate login', async () => {
    vi.useFakeTimers()
    try {
      localStorage.setItem('ai4ml-active-team-id', 'team-1')
      localStorage.setItem(MEMBERSHIP_CACHE_KEY, JSON.stringify({
        user_id: 'user-1',
        cached_at: Date.now(),
        memberships: [{ id: 'team-1', team_id: 'team-1', name: 'Team 1', role: 'admin', member_status: 'active' }],
      }))
      supabase.from.mockClear()
      supabase.auth.signInWithPassword.mockClear()
      supabase.auth.signUp.mockClear()

      const result = await register({
        email: 'new-user@example.test',
        display_name: 'New User',
        password: '123456',
      })

      expect(result.session?.access_token).toBe('token')
      expect(supabase.auth.signUp).toHaveBeenCalledTimes(1)
      expect(supabase.auth.signInWithPassword).not.toHaveBeenCalled()
      expect(supabase.from).not.toHaveBeenCalled()
    } finally {
      vi.clearAllTimers()
      vi.useRealTimers()
    }
  })

  it('builds notifications for exhausted quota and waiting human confirmation', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/quotas/me')) {
        return jsonResponse({
          quota: {
            scope_type: 'member',
            user_id: 'user-1',
            token_quota: 100,
            token_used: 100,
            token_remaining: 0,
            status: 'exhausted',
          },
        })
      }
      if (text.endsWith('/api/teams/team-1/tasks?runtime_only=true')) {
        return jsonResponse({
          items: [baseTask({ id: 'task-2', name: 'Needs review', status: 'waiting_human' })],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const notifications = await getNotifications()
    const count = await getUnreadNotificationCount()

    expect(notifications.items.map((item) => item.category)).toEqual(['quota', 'human'])
    expect(notifications.items[0].notification_id).toBe('quota-exhausted:team-1:user-1')
    expect(count.count).toBe(1)
  })

  it('reuses warmed notifications and applies local read state', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/quotas/me')) {
        return jsonResponse({
          quota: {
            scope_type: 'member',
            user_id: 'user-1',
            token_quota: 100,
            token_used: 100,
            token_remaining: 0,
            status: 'exhausted',
          },
        })
      }
      if (text.endsWith('/api/teams/team-1/tasks?runtime_only=true')) {
        return jsonResponse({
          items: [baseTask({ id: 'task-2', name: 'Needs review', status: 'waiting_human' })],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await warmupNotifications()
    const first = await getNotifications()
    await markAllNotificationsRead(first.items.map((item) => item.notification_id))
    const second = await getNotifications()

    expect(first.items).toHaveLength(2)
    expect(second.items.every((item) => item.is_read)).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('keeps unread notification count lightweight by not loading tasks', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/quotas/me')) {
        return jsonResponse({
          quota: {
            scope_type: 'member',
            user_id: 'user-1',
            token_quota: 100,
            token_used: 100,
            token_remaining: 0,
            status: 'exhausted',
          },
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const count = await getUnreadNotificationCount()

    expect(count.count).toBe(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/quotas/me')
  })

  it('loads the current profile quota without requesting the full quota list', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/quotas/me')) {
        return jsonResponse({
          quota: {
            user_id: 'user-1',
            scope_type: 'member',
            scope_key: 'user-1',
            token_quota: 100,
            token_used: 25,
            token_remaining: 75,
            status: 'active',
          },
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const profile = await getProfile()
    const cachedProfile = await getProfile()

    expect(profile.user_id).toBe('user-1')
    expect(profile.token_quota).toBe(100)
    expect(profile.token_used).toBe(25)
    expect(profile.token_remaining).toBe(75)
    expect(cachedProfile.token_remaining).toBe(75)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/quotas/me')
  })

  it('loads base profile data without blocking on the quota endpoint', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      throw new Error(`unexpected fetch: ${url}`)
    })

    const profile = await getProfileBase()

    expect(profile.user_id).toBe('user-1')
    expect(profile.role).toBe('admin')
    expect(profile.quota_loaded).toBe(false)
    expect(profile.token_quota).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('preloads the profile quota cache for later profile views', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/quotas/me')) {
        return jsonResponse({
          quota: {
            user_id: 'user-1',
            scope_type: 'member',
            token_quota: 200,
            token_used: 40,
            token_remaining: 160,
            status: 'active',
          },
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await warmupProfileQuota()
    const profile = await getProfile()

    expect(profile.token_remaining).toBe(160)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('deduplicates concurrent profile quota requests', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const quotaResponse = deferred()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/quotas/me')) return quotaResponse.promise
      throw new Error(`unexpected fetch: ${text}`)
    })

    const firstProfile = getProfile()
    const secondProfile = getProfile()
    await nextTick()

    expect(fetchMock).toHaveBeenCalledTimes(1)

    quotaResponse.resolve(response({
      quota: {
        user_id: 'user-1',
        scope_type: 'member',
        token_quota: 300,
        token_used: 75,
        token_remaining: 225,
        status: 'active',
      },
    }))

    const [first, second] = await Promise.all([firstProfile, secondProfile])

    expect(first.token_remaining).toBe(225)
    expect(second.token_remaining).toBe(225)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('loads my tasks from the saved team without refetching Supabase memberships', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    supabase.from.mockClear()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks?compact=true')) {
        return jsonResponse({
          items: [
            baseTask({ id: 'task-owned', created_by: 'user-1' }),
            baseTask({ id: 'task-shared', created_by: null }),
            baseTask({ id: 'task-other', created_by: 'user-2' }),
          ],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const tasks = await getMyTasks()

    expect(tasks.map((item) => item.task_id)).toEqual(['task-owned', 'task-shared'])
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(supabase.from).not.toHaveBeenCalled()
  })

  it('loads workspace tasks through the runtime-only task list without filling the full list cache', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks?runtime_only=true')) {
        return jsonResponse({
          items: [baseTask({ id: 'task-running', created_by: 'user-1', status: 'running' })],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const tasks = await getWorkspaceTasks()

    expect(tasks.map((item) => item.task_id)).toEqual(['task-running'])
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(localStorage.setItem).not.toHaveBeenCalledWith(
      expect.stringContaining('ai4ml-task-list-cache'),
      expect.any(String),
    )
  })

  it('reuses a fresh task list cache across callers', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks?compact=true')) {
        return jsonResponse({
          items: [baseTask({ id: 'task-1', created_by: 'user-1' })],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const first = await getTasks()
    const second = await getMyTasks()

    expect(first.items.map((item) => item.task_id)).toEqual(['task-1'])
    expect(second.map((item) => item.task_id)).toEqual(['task-1'])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('can bypass the task list cache for state-changing checks', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    let requestCount = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks?compact=true')) {
        requestCount += 1
        return jsonResponse({
          items: [baseTask({ id: `task-${requestCount}`, created_by: 'user-1' })],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await getTasks()
    const refreshed = await getTasks({ forceRefresh: true })

    expect(refreshed.items.map((item) => item.task_id)).toEqual(['task-2'])
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('builds admin users from supplied member data without refetching members', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/quotas')) {
        return jsonResponse({
          items: [{
            scope_type: 'member',
            user_id: 'user-1',
            token_quota: 100,
            token_used: 20,
            token_remaining: 80,
            status: 'active',
          }],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const result = await getUsers({
      memberData: {
        items: [{
          user_id: 'user-1',
          display_name: 'Alice',
          email: 'alice@example.test',
          role: 'admin',
          member_status: 'active',
        }],
      },
    })

    expect(result.items[0]).toMatchObject({
      user_id: 'user-1',
      display_name: 'Alice',
      token_quota: 100,
      token_used: 20,
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/quotas')
  })

  it('preloads team admin settings and members for later admin tabs', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/settings')) {
        return jsonResponse({ team: { id: 'team-1', name: 'Team A', invite_code: 'JOIN' } })
      }
      if (text.endsWith('/api/teams/team-1/members')) {
        return jsonResponse({
          team_id: 'team-1',
          items: [{
            user_id: 'user-1',
            role: 'admin',
            member_status: 'active',
            profile: { display_name: 'Alice', email: 'alice@example.test' },
          }],
        })
      }
      if (text.endsWith('/api/teams/team-1/admin/platform-limits')) {
        return jsonResponse({ max_task_time_budget_s: 120 })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await warmupTeamAdminCaches({ includeSystemAdmin: true })
    const settings = await getTeamSettings()
    const members = await getTeamMembers()

    expect(settings.name).toBe('Team A')
    expect(members.items[0].display_name).toBe('Alice')
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('serves stale team admin settings immediately while refreshing in the background', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    localStorage.setItem('ai4ml-team-admin-cache-v1:team-1:settings', JSON.stringify({
      cached_at: Date.now() - 11 * 60 * 1000,
      value: { id: 'team-1', name: 'Cached Team', invite_code: 'OLD' },
    }))
    const refresh = deferred()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/settings')) return refresh.promise
      throw new Error(`unexpected fetch: ${text}`)
    })

    const settings = await getTeamSettings()

    expect(settings.name).toBe('Cached Team')
    expect(fetchMock).toHaveBeenCalledTimes(1)

    refresh.resolve(response({ team: { id: 'team-1', name: 'Fresh Team', invite_code: 'NEW' } }))
    await nextTick()
    await nextTick()

    const refreshedSettings = await getTeamSettings()

    expect(refreshedSettings.name).toBe('Fresh Team')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('deduplicates concurrent team admin warmup and reads', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    let settingsCalls = 0
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/settings')) {
        settingsCalls += 1
        await Promise.resolve()
        return jsonResponse({ team: { id: 'team-1', name: 'Team A' } })
      }
      if (text.endsWith('/api/teams/team-1/members')) {
        return jsonResponse({ team_id: 'team-1', items: [] })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const warmup = warmupTeamAdminCaches()
    const settings = await getTeamSettings()
    await warmup

    expect(settings.name).toBe('Team A')
    expect(settingsCalls).toBe(1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not report paused or human-waiting tasks as blocking active tasks', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks?compact=true')) {
        return jsonResponse({
          items: [
            baseTask({ id: 'task-paused', status: 'paused_for_review' }),
            baseTask({ id: 'task-waiting', status: 'waiting_human' }),
          ],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await expect(getActiveTask()).resolves.toBeNull()
  })

  it('marks current notifications read without refetching them', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')

    await expect(markAllNotificationsRead(['quota-exhausted:team-1:user-1'])).resolves.toEqual({ ok: true })

    expect(fetchMock).not.toHaveBeenCalled()
    expect(JSON.parse(localStorage.getItem('ai4ml-read-system-notifications'))).toEqual([
      'quota-exhausted:team-1:user-1',
    ])
  })

  it('loads runtime snapshots through the lightweight endpoint', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.includes('/tasks/task-1/runtime-snapshot')) {
        return jsonResponse({
          task: baseTask(),
          task_run: {
            steps: [{ id: 's1', name: 'data_analysis', node: 'data_analysis', title: 'Data analysis', agent_role: 'Data analysis', status: 'completed' }],
            metrics: { accuracy: 0.9 },
            progress_percent: 40,
          },
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const snapshot = await getTaskRuntimeSnapshot('task-1')

    expect(snapshot.task.task_id).toBe('task-1')
    expect(snapshot.task_run.steps).toHaveLength(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/runtime-snapshot')
  })

  it('can request a fast runtime snapshot without synchronous Codex sync', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.includes('/tasks/task-1/runtime-snapshot?sync=false')) {
        return jsonResponse({
          task: baseTask(),
          task_run: { steps: [], metrics: {}, progress_percent: 14 },
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const snapshot = await getTaskRuntimeSnapshot('task-1', { sync: false })

    expect(snapshot.task.task_id).toBe('task-1')
    expect(snapshot.task_run.progress_percent).toBe(14)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('can request a fast runtime snapshot with a lightweight task summary', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.includes('/tasks/task-1/runtime-snapshot?sync=false&task_detail=summary')) {
        return jsonResponse({
          task: baseTask(),
          task_run: { steps: [], metrics: {}, progress_percent: 18 },
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const snapshot = await getTaskRuntimeSnapshot('task-1', { sync: false, taskDetail: 'summary' })

    expect(snapshot.task.task_id).toBe('task-1')
    expect(snapshot.task_run.progress_percent).toBe(18)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('loads metrics through a fast runtime snapshot without synchronous Codex sync', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.includes('/tasks/task-1/runtime-snapshot?sync=false')) {
        return jsonResponse({
          task: baseTask(),
          task_run: { steps: [], metrics: { accuracy: 0.91 }, progress_percent: 70 },
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const metrics = await getMetrics('task-1')

    expect(metrics.values).toEqual({ accuracy: 0.91 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('creates a task, uploads the selected file as FormData, then starts the run', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const file = new File(['excel-bytes'], 'ENB2012_data.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    const formData = new FormData()
    formData.append('requirement', 'Train a compact multi-output regressor')
    formData.append('target_column', 'Y1,Y2')
    formData.append('task_type', 'regression')
    formData.append('time_budget_s', '20')
    formData.append('file', file)

    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks?compact=true') && !options?.method) {
        return jsonResponse({ items: [] })
      }
      if (text.endsWith('/api/teams/team-1/tasks') && options?.method === 'POST') {
        const body = JSON.parse(String(options.body || '{}'))
        expect(body.description).toBe('Train a compact multi-output regressor')
        expect(body.label_column).toBeNull()
        expect(body.problem_type).toBe('regression')
        expect(body.structured_requirements.target_definition).toEqual({
          target_mode: 'multi_target',
          target_columns: ['Y1', 'Y2'],
          source: 'user_input',
        })
        return jsonResponse(baseTask({ id: 'task-upload', status: 'draft', name: body.name }), 201)
      }
      if (text.includes('/api/teams/team-1/tasks/task-upload/dataset?') && options?.method === 'POST') {
        expect(options.body).toBeInstanceOf(FormData)
        expect(options.body.get('file')).toBe(file)
        return jsonResponse(baseTask({ id: 'task-upload', status: 'uploaded', dataset_filename: 'ENB2012_data.xlsx' }))
      }
      if (text.endsWith('/api/teams/team-1/tasks/task-upload/run?async_start=true') && options?.method === 'POST') {
        const body = JSON.parse(String(options.body || '{}'))
        expect(body.time_limit).toBe(20)
        return jsonResponse(baseTask({ id: 'task-upload', status: 'running', codex_status: 'starting' }))
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const result = await createTask(formData)

    expect(result.task_id).toBe('task-upload')
    expect(result.status).toBe('running')
    expect(fetchMock).toHaveBeenCalledTimes(4)
  })

  it('prefers Codex-native steps from runtime snapshots', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.includes('/tasks/task-1/runtime-snapshot')) {
        return jsonResponse({
          task: baseTask({ executor_type: 'codex' }),
          task_run: {
            steps: [{ id: 'legacy', name: 'training_validation', status: 'running' }],
            codex: {
              workspace_path: 'D:\\333\\AI4ML\\codex_use\\workspaces\\task-1',
              steps: [{ id: 'plan_ready', title: '计划已生成', status: 'waiting_plan_approval', detail: '等待确认' }],
            },
          },
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const snapshot = await getTaskRuntimeSnapshot('task-1')

    expect(snapshot.task_run.steps).toHaveLength(1)
    expect(snapshot.task_run.steps[0]).toMatchObject({
      id: 'plan_ready',
      title: '计划已生成',
      status: 'waiting_human',
      agent_role: 'OURAI',
    })
    expect(snapshot.task_run.codex.workspace_path).toContain('codex_use')
  })

  it('does not show stale human-gated steps when there are no open requests', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.includes('/tasks/task-1/runtime-snapshot')) {
        return jsonResponse({
          task: baseTask({ status: 'running' }),
          task_run: {
            open_request_count: 0,
            steps: [{ id: 'training_validation', name: 'training_validation', status: 'waiting_human' }],
          },
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const snapshot = await getTaskRuntimeSnapshot('task-1')

    expect(snapshot.task_run.steps[0]).toMatchObject({
      id: 'training_validation',
      status: 'pending',
    })
  })

  it('continues a human-gated task after the final approval', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks/task-1/human-collaboration')) {
        return jsonResponse({
          task: baseTask({ status: 'waiting_human' }),
          open_request_count: 1,
          requests: [{
            id: 'request-1',
            status: 'open',
            stage: 'training_validation',
            payload: { policy_id: 'before-run-human-confirmation', request_type: 'stage_checkpoint' },
          }],
        })
      }
      if (text.endsWith('/api/teams/team-1/tasks/task-1/human-requests/request-1/decision')) {
        return jsonResponse({
          task: baseTask({ status: 'planning' }),
          open_request_count: 0,
        })
      }
      if (text.endsWith('/api/teams/team-1/tasks/task-1/run?async_start=true')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body.resume_after_human).toBe(true)
        return jsonResponse(baseTask({ status: 'running' }))
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const result = await submitHitl('task-1', { action: 'verify', adjustments: {} })

    expect(result.status).toBe('running')
    expect(result.continued_run).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('submits Codex improvement decisions and resumes with the selected decision', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks/task-1/human-collaboration')) {
        return jsonResponse({
          task: baseTask({ status: 'paused_for_review' }),
          open_request_count: 1,
          requests: [{
            id: 'request-2',
            status: 'open',
            stage: 'training_validation',
            payload: { request_type: 'codex_improvement_review' },
          }],
        })
      }
      if (text.endsWith('/api/teams/team-1/tasks/task-1/human-requests/request-2/decision')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body.action).toBe('skip')
        expect(body.details.improvement_decision).toBe('stop_and_report')
        return jsonResponse({
          task: baseTask({ status: 'paused_for_review' }),
          open_request_count: 0,
        })
      }
      if (text.endsWith('/api/teams/team-1/tasks/task-1/run?async_start=true')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body.resume_interrupted).toBe(true)
        expect(body.improvement_decision).toBe('stop_and_report')
        return jsonResponse(baseTask({ status: 'running' }))
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const result = await submitHitl('task-1', { action: 'stop_and_report', adjustments: {} })

    expect(result.status).toBe('running')
    expect(result.continued_run).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('continues Codex resume requests through the async run path', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks/task-1/run?async_start=true')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body.resume_interrupted).toBe(true)
        expect(body.improvement_decision).toBe('continue_improvement')
        return jsonResponse(baseTask({ status: 'running', codex_status: 'starting' }))
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const result = await rerunTask('task-1', {}, {
      resume_interrupted: true,
      improvement_decision: 'continue_improvement',
    })

    expect(result.status).toBe('running')
    expect(result.codex_status).toBe('starting')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('publishes task prompts with the prompt asset type', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/assets')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body.asset_type).toBe('prompt')
        expect(body.title).toBe('Prompt A')
        expect(body.source_task_id).toBe('task-1')
        expect(body.metadata.prompt_description).toBe('Use this task description.')
        return jsonResponse({ asset: baseAsset(body) }, 201)
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const result = await publishPrompt('task-1', {
      name: 'Prompt A',
      description: 'Use this task description.',
    })

    expect(result.asset_type).toBe('prompt')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('publishes provided plans without reloading the runtime snapshot', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/assets')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body.asset_type).toBe('plan')
        expect(body.title).toBe('Plan A')
        expect(body.metadata.plan_text).toBe('Run the validated plan.')
        expect(body.metadata.task_type).toBe('classification')
        return jsonResponse({ asset: baseAsset(body) }, 201)
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const result = await publishPlan('task-1', {
      name: 'Plan A',
      description: 'Use this plan.',
      plan_text: 'Run the validated plan.',
      task_category: 'classification',
    })

    expect(result.asset_type).toBe('plan')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('falls back to a fast runtime snapshot when publishing a plan without provided text', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks/task-1/runtime-snapshot?sync=false')) {
        return jsonResponse({
          task: baseTask({ id: 'task-1', problem_type: 'classification' }),
          task_run: { codex: { plan_text: 'Snapshot plan.' } },
        })
      }
      if (text.endsWith('/api/teams/team-1/assets')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body.asset_type).toBe('plan')
        expect(body.metadata.plan_text).toBe('Snapshot plan.')
        return jsonResponse({ asset: baseAsset(body) }, 201)
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const result = await publishPlan('task-1', {
      name: 'Plan A',
      description: 'Use this plan.',
    })

    expect(result.asset_type).toBe('plan')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('loads community prompts and plans through one asset list request', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/assets?visibility=team')) {
        return jsonResponse({
          items: [
            baseAsset({ id: 'prompt-1', asset_type: 'prompt', title: 'Prompt A' }),
            baseAsset({
              id: 'plan-1',
              asset_type: 'plan',
              title: 'Plan A',
            }),
          ],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const assets = await getCommunityAssets(false)
    const cachedAssets = await getCommunityAssets(false)

    expect(assets.prompts.map((item) => item.prompt_id)).toEqual(['prompt-1'])
    expect(assets.plans.map((item) => item.plan_id)).toEqual(['plan-1'])
    expect(assets.plans[0].plan_text).toBe('')
    expect(cachedAssets.prompts.map((item) => item.prompt_id)).toEqual(['prompt-1'])
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('preloads both team-visible and admin asset lists', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/assets?visibility=team')) {
        return jsonResponse({
          items: [baseAsset({ id: 'prompt-visible', asset_type: 'prompt', title: 'Visible prompt' })],
        })
      }
      if (text.endsWith('/api/teams/team-1/assets')) {
        return jsonResponse({
          items: [baseAsset({ id: 'prompt-all', asset_type: 'prompt', title: 'All prompt' })],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await warmupCommunityAssetCaches({ includePending: true })
    const visibleAssets = await getCommunityAssets(false)
    const adminAssets = await getCommunityAssets(true)

    expect(visibleAssets.prompts.map((item) => item.prompt_id)).toEqual(['prompt-visible'])
    expect(adminAssets.prompts.map((item) => item.prompt_id)).toEqual(['prompt-all'])
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('loads plan detail through the single asset detail endpoint', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/assets/plan-1')) {
        return jsonResponse({
          asset: baseAsset({
            id: 'plan-1',
            asset_type: 'plan',
            title: 'Plan A',
            metadata: { plan_text: 'Use Codex.' },
          }),
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const plan = await getPlanDetail('plan-1')

    expect(plan.plan_id).toBe('plan-1')
    expect(plan.plan_text).toBe('Use Codex.')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('loads Codex plan text through the lightweight plan endpoint', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks/task-1/codex-plan')) {
        return jsonResponse({
          task_id: 'task-1',
          task_name: 'Task 1',
          available: true,
          plan_text: '# Plan',
          workspace_path: 'D:/runs/task-1',
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const plan = await getCodexPlan('task-1')

    expect(plan.plan_text).toBe('# Plan')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps missing editable code artifacts as a local unavailable state', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks/task-no-code/code-workspace')) {
        return jsonResponse({ items: [] })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const code = await getOperationCode('task-no-code')

    expect(code).toMatchObject({
      content: '',
      editable: false,
      detail: '当前任务还没有可编辑源码。',
    })
    await expect(updateOperationCode('task-no-code', 'print(1)')).rejects.toThrow('当前任务还没有可编辑源码')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('loads prediction delivery without synchronous task sync', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks/task-1?sync=false')) {
        return jsonResponse(baseTask({
          label_column: 'target',
          dataset_profile: {
            columns: [
              { name: 'feature_a', inferred_type: 'number' },
              { name: 'target', inferred_type: 'number' },
            ],
            preview_rows: [{ feature_a: 12, target: 1 }],
          },
        }))
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const delivery = await getDelivery('task-1')

    expect(delivery.required_features).toEqual(['feature_a'])
    expect(delivery.sample_rows).toEqual([{ feature_a: 12 }])
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('sync=false')
  })

  it('sends only changed user quota fields to admin update', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/admin/users/user-2')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body).toEqual({ token_quota: 1200 })
        return jsonResponse({ detail: 'ok', member: {}, quota: {} })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await updateUser('user-2', {
      display_name: 'Alice',
      original_display_name: 'Alice',
      role: 'business',
      original_native_role: 'business_user',
      token_quota: 1200,
      original_token_quota: 1000,
      is_active: true,
      original_is_active: true,
      original_quota_status: 'active',
      warning_threshold: 0,
      original_warning_threshold: 0,
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('reactivates exhausted quota when an admin increases the quota above usage', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/admin/users/user-2')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body).toEqual({ token_quota: 1200, quota_status: 'active' })
        return jsonResponse({ detail: 'ok', member: {}, quota: {} })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await updateUser('user-2', {
      display_name: 'Alice',
      original_display_name: 'Alice',
      role: 'business',
      original_native_role: 'business_user',
      token_quota: 1200,
      original_token_quota: 1000,
      token_used: 1000,
      is_active: true,
      original_is_active: true,
      original_quota_status: 'exhausted',
      warning_threshold: 0,
      original_warning_threshold: 0,
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('updates model config without sending returned auth json', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/model-config')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body).toEqual({
          display_name: 'AIOUR',
          api_key: '',
          config_toml: 'model = "gpt-5"\n',
        })
        return jsonResponse({
          display_name: 'AIOUR',
          auth_json: '',
          config_toml: 'model = "gpt-5"\n',
          auth_path: 'auth.json',
          config_path: 'config.toml',
          auth_configured: true,
          auth_key_preview: '已配置（末尾 1234）',
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await updateModelConfig({
      display_name: 'AIOUR',
      auth_json: '{"OPENAI_API_KEY":"should-not-send"}',
      api_key: '',
      config_toml: 'model = "gpt-5"\n',
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('does not demote team owner when saving an unchanged owner row', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/admin/users/owner-1')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body).toEqual({})
        return jsonResponse({ detail: 'ok', member: {}, quota: {} })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    await updateUser('owner-1', {
      display_name: 'Owner',
      original_display_name: 'Owner',
      role: 'admin',
      original_native_role: 'team_owner',
      token_quota: 0,
      original_token_quota: 0,
      is_active: true,
      original_is_active: true,
      original_quota_status: 'active',
      warning_threshold: 0,
      original_warning_threshold: 0,
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

function jsonResponse(payload, status = 200) {
  return Promise.resolve(response(payload, status))
}

function response(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function deferred() {
  let resolve
  const promise = new Promise((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function nextTick() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function baseTask(overrides = {}) {
  return {
    id: 'task-1',
    team_id: 'team-1',
    created_by: 'user-1',
    name: 'Task 1',
    description: 'Train a classifier',
    status: 'running',
    created_at: '2026-05-19T00:00:00Z',
    updated_at: '2026-05-19T00:00:00Z',
    ...overrides,
  }
}

function baseAsset(overrides = {}) {
  return {
    id: 'asset-1',
    team_id: 'team-1',
    created_by: 'user-1',
    asset_type: 'prompt',
    title: 'Prompt A',
    description: '',
    tags: [],
    visibility: 'team',
    review_status: 'published',
    metadata: {},
    created_at: '2026-05-19T00:00:00Z',
    updated_at: '2026-05-19T00:00:00Z',
    ...overrides,
  }
}

function supabaseTableMock(table) {
  const query = {
    select: vi.fn(() => query),
    eq: vi.fn(() => query),
    in: vi.fn(() => query),
    order: vi.fn(async () => {
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
    query.in = vi.fn(async () => ({
      data: [{ id: 'team-1', name: 'Team 1', role: 'admin', member_status: 'active' }],
      error: null,
    }))
  }
  return query
}
