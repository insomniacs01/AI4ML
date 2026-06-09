import { afterEach, describe, expect, it, vi } from 'vitest'
import { warmupProfileQuota } from '@/api/auth'
import { warmupCommunityAssetCaches } from '@/api/community'
import { warmupTaskCache } from '@/api/taskCache'
import { warmupTeamAdminCaches } from '@/api/teamAdmin'
import { warmupWorkspaceCache } from '@/api/workspaceWarmup'
import { warmupAuthenticatedExperienceSoon } from './startupWarmup'

vi.mock('@/api/auth', () => ({ warmupProfileQuota: vi.fn(() => Promise.resolve()) }))
vi.mock('@/api/community', () => ({ warmupCommunityAssetCaches: vi.fn(() => Promise.resolve()) }))
vi.mock('@/api/taskCache', () => ({ warmupTaskCache: vi.fn(() => Promise.resolve()) }))
vi.mock('@/api/teamAdmin', () => ({ warmupTeamAdminCaches: vi.fn(() => Promise.resolve()) }))
vi.mock('@/api/workspaceWarmup', () => ({ warmupWorkspaceCache: vi.fn(() => Promise.resolve()) }))

afterEach(() => {
  vi.clearAllMocks()
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('startup warmup', () => {
  it('stagger-warms authenticated caches once per minute', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(1_000_000)

    warmupAuthenticatedExperienceSoon({ isAdmin: true })
    warmupAuthenticatedExperienceSoon({ isAdmin: true })

    expect(warmupWorkspaceCache).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(6000)

    expect(warmupWorkspaceCache).toHaveBeenCalledTimes(1)
    expect(warmupTaskCache).toHaveBeenCalledTimes(1)
    expect(warmupCommunityAssetCaches).toHaveBeenCalledTimes(1)
    expect(warmupCommunityAssetCaches).toHaveBeenCalledWith({ includePending: true })
    expect(warmupTeamAdminCaches).toHaveBeenCalledTimes(1)
    expect(warmupTeamAdminCaches).toHaveBeenCalledWith({ includeSystemAdmin: true })
    expect(warmupProfileQuota).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000)
  })
})
