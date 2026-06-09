import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  isTaskListCacheFresh,
  readTaskListCache,
  clearTaskListCache,
  taskListCacheKey,
  writeTaskListCache,
} from './taskListCache'

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

describe('task list cache', () => {
  it('keys cached task lists by user and team', () => {
    expect(taskListCacheKey({ userId: 'user-1', teamId: 'team-1' })).toBe('ai4ml-task-list-cache:user-1:team-1')
    expect(taskListCacheKey({ userId: 'user-1' })).toBe('')
  })

  it('stores compact task rows and restores them before refresh', () => {
    const context = { userId: 'user-1', teamId: 'team-1' }

    writeTaskListCache(context, [{
      task_id: 'task-1',
      status: 'completed',
      dataset_profile: { columns: new Array(100).fill({ name: 'x' }) },
      structured_requirements: { large: true },
      last_run_attempt: { logs: new Array(50).fill('large') },
    }], 1000)

    const cached = readTaskListCache(context, 2000)

    expect(cached.cachedAt).toBe(1000)
    expect(cached.tasks[0]).toMatchObject({ task_id: 'task-1', status: 'completed' })
    expect(cached.tasks[0].dataset_profile).toBeUndefined()
    expect(cached.tasks[0].structured_requirements).toBeUndefined()
    expect(cached.tasks[0].last_run_attempt).toBeUndefined()
  })

  it('separates fresh cache from expired cache', () => {
    expect(isTaskListCacheFresh(1000, 30_000)).toBe(true)
    expect(isTaskListCacheFresh(1000, 70_000)).toBe(false)

    const context = { userId: 'user-1', teamId: 'team-1' }
    writeTaskListCache(context, [{ task_id: 'task-1' }], 0)

    expect(readTaskListCache(context, 25 * 60 * 60 * 1000)).toBeNull()
  })

  it('clears the current task list cache entry', () => {
    const context = { userId: 'user-1', teamId: 'team-1' }
    writeTaskListCache(context, [{ task_id: 'task-1' }], 1000)

    clearTaskListCache(context)

    expect(readTaskListCache(context, 1000)).toBeNull()
  })
})
