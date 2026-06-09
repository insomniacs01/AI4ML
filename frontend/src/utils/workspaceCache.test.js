import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  isWorkspaceRuntimeCacheFresh,
  readWorkspaceCache,
  workspaceCacheAgeText,
  workspaceCacheKey,
  writeWorkspaceCache,
} from './workspaceCache'

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

afterEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe('workspace cache', () => {
  it('keys cached workspace snapshots by user and team', () => {
    expect(workspaceCacheKey({ userId: 'user-1', teamId: 'team-1' })).toBe('ai4ml-workspace-cache:user-1:team-1')
    expect(workspaceCacheKey({ userId: 'user-1' })).toBe('')
    expect(workspaceCacheKey(null)).toBe('')
  })

  it('stores and restores the last real workspace snapshot', () => {
    const context = { userId: 'user-1', teamId: 'team-1' }
    const now = 1_000_000

    const written = writeWorkspaceCache(context, {
      tasks: [{ task_id: 'task-1', status: 'running' }],
      activeTaskId: 'task-1',
      task: { task_id: 'task-1', status: 'running' },
      taskRun: { progress_percent: 40 },
      steps: [{ id: 'step-1', status: 'running' }],
    }, now)

    expect(written).toBe(true)
    expect(readWorkspaceCache(context, now + 5000)).toMatchObject({
      cachedAt: now,
      activeTaskId: 'task-1',
      task: { task_id: 'task-1', status: 'running' },
      taskRun: { progress_percent: 40 },
      steps: [{ id: 'step-1', status: 'running' }],
    })
  })

  it('strips detail-only task payloads before storing workspace snapshots', () => {
    const context = { userId: 'user-1', teamId: 'team-1' }

    writeWorkspaceCache(context, {
      tasks: [{
        task_id: 'task-1',
        status: 'running',
        dataset_profile: { columns: new Array(100).fill({ name: 'x' }) },
        structured_requirements: { large: true },
      }],
      task: {
        task_id: 'task-1',
        status: 'running',
        dataset_profile: { row_count: 1000 },
        last_run_attempt: { token_usage: { total_tokens: 1000 } },
      },
      taskRun: {
        progress_percent: 40,
        codex: {
          session_id: 'session-1',
          token_usage: { sessions: new Array(20).fill({ total_tokens: 1 }) },
        },
      },
    }, 1000)

    const cached = readWorkspaceCache(context, 1000)

    expect(cached.tasks[0].dataset_profile).toBeUndefined()
    expect(cached.tasks[0].structured_requirements).toBeUndefined()
    expect(cached.task.dataset_profile).toBeUndefined()
    expect(cached.task.last_run_attempt).toBeUndefined()
    expect(cached.taskRun.codex).toEqual({ session_id: 'session-1' })
  })

  it('rejects expired or invalid snapshots instead of inventing data', () => {
    const context = { userId: 'user-1', teamId: 'team-1' }
    writeWorkspaceCache(context, { task: { task_id: 'task-1' } }, 0)

    expect(readWorkspaceCache(context, 25 * 60 * 60 * 1000)).toBeNull()

    localStorage.setItem(workspaceCacheKey(context), '{broken')
    expect(readWorkspaceCache(context, 1)).toBeNull()
  })

  it('formats cache age for the workspace sync label', () => {
    expect(workspaceCacheAgeText(1000, 42_000)).toBe('41 秒前')
    expect(workspaceCacheAgeText(1000, 181_000)).toBe('3 分钟前')
    expect(workspaceCacheAgeText(1000, 7_201_000)).toBe('2 小时前')
  })

  it('marks runtime cache freshness separately from cache validity', () => {
    expect(isWorkspaceRuntimeCacheFresh(1000, 30_000)).toBe(true)
    expect(isWorkspaceRuntimeCacheFresh(1000, 32_000)).toBe(false)
    expect(isWorkspaceRuntimeCacheFresh(null, 32_000)).toBe(false)
  })
})
