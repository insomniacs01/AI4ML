import { afterEach, describe, expect, it, vi } from 'vitest'
import { warmupAuthenticatedExperienceSoon } from './startupWarmup'

const routeChunkImports = vi.hoisted(() => ({
  admin: vi.fn(),
  community: vi.fn(),
  createTask: vi.fn(),
  myAssets: vi.fn(),
  profile: vi.fn(),
  taskDetail: vi.fn(),
  tasks: vi.fn(),
  workspace: vi.fn(),
}))

vi.mock('@/views/AdminView.vue', () => {
  routeChunkImports.admin()
  return { default: {} }
})
vi.mock('@/views/CommunityView.vue', () => {
  routeChunkImports.community()
  return { default: {} }
})
vi.mock('@/views/CreateTaskView.vue', () => {
  routeChunkImports.createTask()
  return { default: {} }
})
vi.mock('@/views/MyAssetsView.vue', () => {
  routeChunkImports.myAssets()
  return { default: {} }
})
vi.mock('@/views/ProfileView.vue', () => {
  routeChunkImports.profile()
  return { default: {} }
})
vi.mock('@/views/TaskDetailView.vue', () => {
  routeChunkImports.taskDetail()
  return { default: {} }
})
vi.mock('@/views/TasksView.vue', () => {
  routeChunkImports.tasks()
  return { default: {} }
})
vi.mock('@/views/WorkspaceView.vue', () => {
  routeChunkImports.workspace()
  return { default: {} }
})

afterEach(() => {
  vi.clearAllMocks()
  vi.clearAllTimers()
  vi.useRealTimers()
})

describe('startup warmup', () => {
  it('preloads route chunks without warming data APIs more than once per minute', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(1_000_000)

    warmupAuthenticatedExperienceSoon({ isAdmin: true })
    warmupAuthenticatedExperienceSoon({ isAdmin: true })

    Object.values(routeChunkImports).forEach((imported) => {
      expect(imported).not.toHaveBeenCalled()
    })

    await vi.advanceTimersByTimeAsync(6000)

    Object.values(routeChunkImports).forEach((imported) => {
      expect(imported).toHaveBeenCalledTimes(1)
    })
  })
})
