<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Bell,
  ArrowLeft,
  ArrowRight,
  ClipboardList,
  Compass,
  LogOut,
  PlusCircle,
  Shield,
  Workflow,
} from 'lucide-vue-next'
import {
  getCurrentUser,
  getModelProfile,
  getNotifications,
  getUnreadNotificationCount,
  logout,
  markAllNotificationsRead,
  markNotificationRead,
} from './api/client'
import { clearAuthCache } from './router'
import { getCachedUser, requireSession } from './api/session'
import { warmupWorkspaceCacheSoon } from './api/workspaceWarmup'
import { setModelDisplayName } from '@/utils/modelProfile'

const route = useRoute()
const router = useRouter()
const user = ref(null)
const loadingUser = ref(false)
const notifications = ref([])
const unreadCount = ref(0)
const notificationOpen = ref(false)
const notificationError = ref('')
const notificationStream = ref(null)
const notificationLoading = ref(false)
const sidebarCollapsed = ref(false)
const modelDisplayName = ref('Codex')
const TOPBAR_REFRESH_MS = 60_000
const TOPBAR_BACKGROUND_DELAY_MS = 1200
let lastUserRefreshAt = 0
let lastNotificationCountAt = 0
let lastModelProfileAt = 0
let modelProfileTimer = null
let unreadCountTimer = null

const isPublic = computed(() => route.meta.public)
const canAccessAdminConsole = computed(() => user.value?.role === 'admin')
const topbarTitle = computed(() => {
  const matched = sidebarNavItems.value.find((item) => route.path === item.path || route.path.startsWith(`${item.path}/`))
  if (route.path === '/admin') return '管理台'
  if (route.path === '/profile') return '个人中心'
  if (route.path.startsWith('/assets')) return '我的资产'
  if (route.path.startsWith('/demo') || route.path.startsWith('/tasks/')) return '任务详情'
  return matched?.label || 'AI4ML'
})
const roleLabel = computed(() => {
  const map = { admin: '系统管理员', community_admin: '社区管理员', developer: '开发者', business: '业务用户' }
  return map[user.value?.role] || '会话'
})
const sidebarNavItems = computed(() => [
  { label: '开始任务', path: '/create', icon: PlusCircle },
  { label: '工作台', path: '/workspace', icon: Workflow },
  { label: '我的任务', path: '/tasks', icon: ClipboardList },
  { label: '社区广场', path: '/community', icon: Compass },
])

function setUserFromSession(sessionUser) {
  if (!sessionUser?.id) return
  const metadata = sessionUser.user_metadata || {}
  user.value = {
    ...(user.value || {}),
    user_id: sessionUser.id,
    email: sessionUser.email,
    display_name: metadata.display_name || sessionUser.email || sessionUser.id,
    role: user.value?.role || 'business',
  }
}

function seedUserFromSession() {
  if (isPublic.value || user.value) return
  const cachedUser = getCachedUser()
  if (cachedUser?.id) {
    setUserFromSession(cachedUser)
    return
  }
  requireSession()
    .then((session) => setUserFromSession(session.user))
    .catch(() => {})
}

async function refreshUser() {
  if (!isPublic.value && user.value && Date.now() - lastUserRefreshAt < TOPBAR_REFRESH_MS) return
  if (isPublic.value) {
    user.value = null
    closeNotificationStream()
    return
  }
  loadingUser.value = !user.value
  try {
    const data = await getCurrentUser()
    user.value = data.user
    lastUserRefreshAt = Date.now()
    scheduleModelProfileRefresh(TOPBAR_BACKGROUND_DELAY_MS)
    scheduleUnreadCountRefresh(TOPBAR_BACKGROUND_DELAY_MS)
    if (route.path !== '/workspace') warmupWorkspaceCacheSoon(TOPBAR_BACKGROUND_DELAY_MS)
    connectNotificationStream()
  } catch {
    if (!user.value) {
      user.value = null
      notifications.value = []
      unreadCount.value = 0
      closeNotificationStream()
    }
  } finally {
    loadingUser.value = false
  }
}

function scheduleModelProfileRefresh(delayMs = 0) {
  if (modelProfileTimer) return
  modelProfileTimer = window.setTimeout(() => {
    modelProfileTimer = null
    refreshModelProfile()
  }, delayMs)
}

async function refreshModelProfile() {
  if (Date.now() - lastModelProfileAt < TOPBAR_REFRESH_MS) return
  lastModelProfileAt = Date.now()
  try {
    const modelProfile = await getModelProfile()
    modelDisplayName.value = modelProfile?.display_name || 'Codex'
    setModelDisplayName(modelDisplayName.value)
  } catch {
    // Keep the previous label when the lightweight profile call fails.
  }
}

function scheduleUnreadCountRefresh(delayMs = 0) {
  if (unreadCountTimer) return
  unreadCountTimer = window.setTimeout(() => {
    unreadCountTimer = null
    refreshUnreadCount()
  }, delayMs)
}

async function refreshUnreadCount() {
  if (!user.value || Date.now() - lastNotificationCountAt < TOPBAR_REFRESH_MS) return
  lastNotificationCountAt = Date.now()
  try {
    const unread = await getUnreadNotificationCount()
    unreadCount.value = Number(unread.count || 0)
  } catch {
    // The notification menu will surface detailed errors when opened.
  }
}

async function handleLogout() {
  await logout()
  clearAuthCache()
  user.value = null
  notifications.value = []
  unreadCount.value = 0
  notificationOpen.value = false
  closeNotificationStream()
  router.push('/login')
}

async function navigateTo(path) {
  if (route.fullPath === path) return
  try {
    await router.push(path)
  } catch {
    window.location.assign(path)
  }
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function closeNotificationStream() {
  if (!notificationStream.value) return
  notificationStream.value.close()
  notificationStream.value = null
}

function applyNotificationPayload(payload) {
  notifications.value = payload.items || []
  const count = payload.unread_count ?? payload.count
  unreadCount.value = Number.isFinite(Number(count))
    ? Number(count)
    : notifications.value.filter((item) => !item.is_read).length
}

async function loadNotifications() {
  if (!user.value) return
  notificationLoading.value = true
  notificationError.value = ''
  try {
    const items = await getNotifications({ limit: 30 })
    applyNotificationPayload({ items: items.items || [] })
    lastNotificationCountAt = Date.now()
  } catch (err) {
    notificationError.value = err.message
  } finally {
    notificationLoading.value = false
  }
}

function connectNotificationStream() {
  closeNotificationStream()
}

async function toggleNotifications() {
  notificationOpen.value = !notificationOpen.value
  if (notificationOpen.value) await loadNotifications()
}

async function markNotification(item) {
  if (!item || item.is_read) return
  try {
    await markNotificationRead(item.notification_id)
    item.is_read = true
    unreadCount.value = Math.max(0, unreadCount.value - 1)
  } catch (err) {
    notificationError.value = err.message
  }
}

async function markAllNotifications() {
  const unreadIds = notifications.value
    .filter((item) => !item.is_read && item.notification_id)
    .map((item) => item.notification_id)
  if (!unreadIds.length) {
    unreadCount.value = 0
    return
  }
  const previousNotifications = notifications.value
  const previousUnreadCount = unreadCount.value
  notifications.value = notifications.value.map((item) => ({ ...item, is_read: true }))
  unreadCount.value = 0
  notificationError.value = ''
  try {
    await markAllNotificationsRead(unreadIds)
  } catch (err) {
    notifications.value = previousNotifications
    unreadCount.value = previousUnreadCount
    notificationError.value = err.message
  }
}

function notificationCategoryLabel(category) {
  return { quota: '额度', human: '待确认', system: '系统' }[category] || '通知'
}

function notificationTarget(item) {
  if (item?.target_path) return { path: item.target_path }
  if (item?.task_id) return { path: '/workspace', query: { task_id: item.task_id } }
  if (!item?.asset_type || !item?.asset_id) return null
  const tab = item.asset_type === 'plan' ? 'plans' : 'prompts'
  return { path: '/community', query: { tab, asset_id: item.asset_id } }
}

async function openNotification(item) {
  await markNotification(item)
  const target = notificationTarget(item)
  notificationOpen.value = false
  if (target) await router.push(target)
}

onMounted(() => {
  seedUserFromSession()
  refreshUser()
})
onBeforeUnmount(() => {
  closeNotificationStream()
  if (modelProfileTimer) window.clearTimeout(modelProfileTimer)
  if (unreadCountTimer) window.clearTimeout(unreadCountTimer)
})
watch(() => route.fullPath, () => {
  notificationOpen.value = false
})
router.afterEach(refreshUser)
</script>

<template>
  <RouterView v-if="isPublic" />
  <div v-else class="app-portal-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <header class="app-topbar">
      <div class="topbar-context">
        <strong>{{ topbarTitle }}</strong>
        <span>模型已就绪：{{ modelDisplayName }}</span>
      </div>
      <div class="topbar-actions">
        <div v-if="canAccessAdminConsole" class="expert-tool-group">
          <span>专家<br />工具</span>
          <button
            class="topbar-admin-button"
            type="button"
            :class="{ active: route.path === '/admin' }"
            @click="navigateTo('/admin')"
          >
            <Shield :size="18" />
            管理台
          </button>
        </div>
        <div v-if="user" class="notification-center">
          <button class="icon-button subtle notification-button" type="button" title="通知" @click="toggleNotifications">
            <Bell :size="18" />
            <span v-if="unreadCount" class="notification-badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</span>
          </button>
          <section v-if="notificationOpen" class="notification-menu">
            <div class="notification-head">
              <strong>系统通知</strong>
              <button class="secondary-action compact-action" type="button" :disabled="!unreadCount" @click="markAllNotifications">全部已读</button>
            </div>
            <p v-if="notificationError" class="form-error">{{ notificationError }}</p>
            <div class="notification-list">
              <button
                v-for="item in notifications"
                :key="item.notification_id"
                class="notification-item"
                :class="{ unread: !item.is_read }"
                type="button"
                @click="openNotification(item)"
              >
                <span>{{ notificationCategoryLabel(item.category) }}</span>
                <strong>{{ item.title }}</strong>
                <small>{{ item.content || item.created_at }}</small>
              </button>
              <p v-if="!notificationLoading && !notifications.length" class="muted">暂无通知</p>
            </div>
          </section>
        </div>
        <button class="user-chip topbar-user user-chip-button" type="button" @click="navigateTo('/profile')">
          <span class="avatar">{{ (user?.display_name || user?.user_id || '?').slice(0, 1) }}</span>
          <span>
            <strong>{{ loadingUser ? '同步中' : user?.display_name || '未登录' }}</strong>
            <small>{{ roleLabel }}</small>
          </span>
        </button>
        <button class="icon-button subtle" type="button" title="退出登录" @click="handleLogout">
          <LogOut :size="18" />
        </button>
      </div>
    </header>

    <div class="portal-body" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
      <aside class="profile-sidebar">
        <div class="sidebar-head">
          <div class="sidebar-brand-mark">AI</div>
          <div class="sidebar-brand-text">
            <strong>AI4ML</strong>
          </div>
          <button
            class="sidebar-toggle"
            type="button"
            :aria-expanded="!sidebarCollapsed"
            :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
            :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
            @click="toggleSidebar"
          >
            <component :is="sidebarCollapsed ? ArrowRight : ArrowLeft" :size="17" />
          </button>
        </div>

        <p class="sidebar-section-label">工作流</p>

        <nav class="nav-stack">
          <button
            v-for="item in sidebarNavItems"
            :key="item.path"
            type="button"
            class="nav-item"
            :class="{ active: route.path === item.path || route.path.startsWith(`${item.path}/`) }"
            :aria-label="sidebarCollapsed ? item.label : undefined"
            :title="item.label"
            @click="navigateTo(item.path)"
          >
            <span class="nav-icon"><component :is="item.icon" :size="18" /></span>
            <span class="nav-label">{{ item.label }}</span>
          </button>
        </nav>
      </aside>

      <main class="page-frame">
        <RouterView class="page-pop-surface" />
      </main>
    </div>
  </div>
</template>
