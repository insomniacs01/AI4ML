import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createTask,
  getActiveTask,
  getMyTasks,
  getNotifications,
  getTaskRuntimeSnapshot,
  getUnreadNotificationCount,
  markAllNotificationsRead,
  predictPublicDemo,
  publishPrompt,
  submitHitl,
  updateUser,
} from './client'
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

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('api client compatibility helpers', () => {
  it('fails explicitly when public demo prediction has no backend implementation', async () => {
    await expect(predictPublicDemo('demo_1', [{ age: 20 }])).rejects.toThrow('尚未接入后端预测接口')
  })

  it('builds notifications for exhausted quota and waiting human confirmation', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/quotas')) {
        return jsonResponse({
          items: [{
            scope_type: 'member',
            user_id: 'user-1',
            token_quota: 100,
            token_used: 100,
            token_remaining: 0,
            status: 'exhausted',
          }],
        })
      }
      if (text.endsWith('/api/teams/team-1/tasks')) {
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

  it('keeps unread notification count lightweight by not loading tasks', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/quotas')) {
        return jsonResponse({
          items: [{
            scope_type: 'member',
            user_id: 'user-1',
            token_quota: 100,
            token_used: 100,
            token_remaining: 0,
            status: 'exhausted',
          }],
        })
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const count = await getUnreadNotificationCount()

    expect(count.count).toBe(1)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/quotas')
  })

  it('loads my tasks from the saved team without refetching Supabase memberships', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    supabase.from.mockClear()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks')) {
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

  it('does not report paused or human-waiting tasks as blocking active tasks', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (url) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks')) {
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
      if (text.endsWith('/api/teams/team-1/tasks') && !options?.method) {
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
      if (text.endsWith('/api/teams/team-1/tasks/task-upload/run') && options?.method === 'POST') {
        const body = JSON.parse(String(options.body || '{}'))
        expect(body.time_limit).toBe(20)
        return jsonResponse(baseTask({ id: 'task-upload', status: 'running' }))
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
      agent_role: 'Codex',
    })
    expect(snapshot.task_run.codex.workspace_path).toContain('codex_use')
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
      if (text.endsWith('/api/teams/team-1/tasks/task-1/run')) {
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

  it('publishes task prompts with the prompt asset type', async () => {
    localStorage.setItem('ai4ml-active-team-id', 'team-1')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (url, options) => {
      const text = String(url)
      if (text.endsWith('/api/teams/team-1/tasks/task-1')) return jsonResponse(baseTask({ status: 'completed' }))
      if (text.endsWith('/api/teams/team-1/assets')) {
        const body = JSON.parse(String(options?.body || '{}'))
        expect(body.asset_type).toBe('prompt')
        expect(body.title).toBe('Prompt A')
        return jsonResponse({ asset: baseAsset(body) }, 201)
      }
      throw new Error(`unexpected fetch: ${text}`)
    })

    const result = await publishPrompt('task-1', {
      name: 'Prompt A',
      description: 'Use this task description.',
    })

    expect(result.asset_type).toBe('prompt')
    expect(fetchMock).toHaveBeenCalledTimes(2)
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
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  }))
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
