import { afterEach, describe, expect, it, vi } from 'vitest'
import { useAdminManagement } from '@/composables/useAdminManagement'
import { getCommunityAssets } from '@/api/community'
import { getMe } from '@/api/auth'
import { getModelConfig } from '@/api/modelConfig'
import { getPlatformLimits, getTeamMembers, getTeamSettings, getUsers } from '@/api/teamAdmin'

vi.mock('@/api/community', () => ({
  deleteCommunityPlan: vi.fn(),
  deleteCommunityPrompt: vi.fn(),
  getCommunityAssets: vi.fn(),
  reviewPlan: vi.fn(),
  reviewPrompt: vi.fn(),
}))

vi.mock('@/api/auth', () => ({
  getMe: vi.fn(),
}))

vi.mock('@/api/modelConfig', () => ({
  getModelConfig: vi.fn(),
  updateModelConfig: vi.fn(),
}))

vi.mock('@/api/teamAdmin', () => ({
  createTeamInvite: vi.fn(),
  getPlatformLimits: vi.fn(),
  getTeamMembers: vi.fn(),
  getTeamSettings: vi.fn(),
  getUsers: vi.fn(),
  resetUserPassword: vi.fn(),
  updatePlatformLimits: vi.fn(),
  updateTeamMemberRole: vi.fn(),
  updateTeamMemberStatus: vi.fn(),
  updateUser: vi.fn(),
}))

afterEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe('useAdminManagement', () => {
  it('loads only the active community section on initial admin load', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    getMe.mockResolvedValue({ user: { user_id: 'user-1', role: 'admin' } })
    getCommunityAssets.mockResolvedValue({ prompts: [{ prompt_id: 'prompt-1', status: 'pending' }], plans: [] })

    const admin = useAdminManagement()
    await admin.load()

    expect(getMe).toHaveBeenCalledTimes(1)
    expect(getCommunityAssets).toHaveBeenCalledWith(true)
    expect(getTeamSettings).not.toHaveBeenCalled()
    expect(getTeamMembers).not.toHaveBeenCalled()
    expect(getUsers).not.toHaveBeenCalled()
    expect(getPlatformLimits).not.toHaveBeenCalled()
    expect(getModelConfig).not.toHaveBeenCalled()
    expect(admin.pendingPromptCount.value).toBe(1)
  })

  it('renders users before quota and platform limits finish loading', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {})
    const memberData = {
      team_id: 'team-1',
      items: [{ user_id: 'user-1', role: 'admin', member_status: 'active' }],
    }
    const quotaRefresh = deferred()
    const limitsRefresh = deferred()
    vi.mocked(getMe).mockResolvedValue({ user: { user_id: 'user-1', role: 'admin' } })
    vi.mocked(getCommunityAssets).mockResolvedValue({ prompts: [], plans: [] })
    vi.mocked(getTeamMembers).mockResolvedValue(memberData)
    vi.mocked(getUsers)
      .mockResolvedValueOnce({ items: [{ user_id: 'user-1', role: 'admin', quota_loaded: false }] })
      .mockReturnValueOnce(quotaRefresh.promise)
    vi.mocked(getPlatformLimits).mockReturnValue(limitsRefresh.promise)

    const admin = useAdminManagement()
    await admin.load()
    await admin.setActiveSection('users')

    expect(getTeamMembers).toHaveBeenCalledTimes(1)
    expect(getUsers).toHaveBeenNthCalledWith(1, { memberData, includeQuotas: false })
    expect(getUsers).toHaveBeenNthCalledWith(2, { memberData })
    expect(getPlatformLimits).toHaveBeenCalledTimes(1)
    expect(getTeamSettings).not.toHaveBeenCalled()
    expect(getModelConfig).not.toHaveBeenCalled()
    expect(admin.sectionLoading.value).toBe(false)
    expect(admin.users.value).toHaveLength(1)
    expect(admin.users.value[0].quota_loaded).toBe(false)
    expect(admin.quotaLoading.value).toBe(true)
    expect(admin.platformLimitsLoading.value).toBe(true)

    quotaRefresh.resolve({ items: [{ user_id: 'user-1', role: 'admin', quota_loaded: true, token_quota: 100 }] })
    limitsRefresh.resolve({
      max_concurrent_tasks_per_user: 3,
      max_queued_tasks_per_user: 4,
      max_task_time_budget_s: 120,
    })
    await Promise.resolve()
    await Promise.resolve()

    expect(admin.quotaLoading.value).toBe(false)
    expect(admin.platformLimitsLoading.value).toBe(false)
    expect(admin.users.value[0].quota_loaded).toBe(true)
    expect(admin.platformLimits.value.max_task_time_budget_s).toBe(120)
  })
})

function deferred() {
  let resolve
  const promise = new Promise((done) => {
    resolve = done
  })
  return { promise, resolve }
}
