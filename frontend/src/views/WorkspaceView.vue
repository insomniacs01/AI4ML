<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ArrowRight, Compass, FileText, FilePlus2, RefreshCw, Settings2, Workflow, XCircle } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import CodexRealtimePanel from '@/components/CodexRealtimePanel.vue'
import HitlApprovalModal from '@/components/HitlApprovalModal.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TaskFlowSteps from '@/components/TaskFlowSteps.vue'
import TaskTimeline from '@/components/TaskTimeline.vue'
import { getHitl, getMyTasks, getTaskRuntimeSnapshot, pauseTask, rerunTask } from '@/api/client'
import { getActiveTeamHint, getCachedUser } from '@/api/session'
import { createCodexRealtimeStream } from '@/composables/useCodexRealtimeStream'
import { displayTaskTitle } from '@/utils/labels'
import {
  createCodexRealtimeState,
  resetCodexRealtimeState,
  seedCodexRealtimeFromSnapshot,
  shouldApplyRealtimeTaskPatch,
} from '@/utils/codexRealtime'
import { modelDisplayName } from '@/utils/modelProfile'
import { taskProgressPercent } from '@/utils/progress'
import { continueRunOptions } from '@/utils/taskRunControl'
import { isFinishedTaskStatus, pickActiveTask, stepStatusLabel, taskIdOf } from '@/utils/taskRecords'
import {
  isWorkspaceRuntimeCacheFresh,
  readWorkspaceCache,
  workspaceCacheAgeText,
  writeWorkspaceCache,
} from '@/utils/workspaceCache'

const router = useRouter()
const tasks = ref([])
const task = ref(null)
const steps = ref([])
const error = ref('')
const loading = ref(false)
const refreshing = ref(false)
const snapshotRefreshing = ref(false)
const hydratedFromCache = ref(false)
const cacheSyncedAt = ref(null)
const pausing = ref(false)
const hitl = ref(null)
const hitlModalOpen = ref(false)
const taskRun = ref(null)
const codexRealtime = ref(createCodexRealtimeState())
let pollTimer = null
let disposed = false
const pausableStatuses = new Set(['running'])
const runtimeActiveStatuses = new Set(['running'])
const startableStatuses = new Set(['uploaded', 'planning'])
const SNAPSHOT_POLL_MS = 30000

const activeTask = computed(() => task.value)
const activeTaskId = computed(() => taskIdOf(activeTask.value))
const finished = computed(() => isFinishedTaskStatus(activeTask.value?.status))
const hasWorkspaceState = computed(() => Boolean(activeTask.value) || tasks.value.length > 0)
const isSyncing = computed(() => refreshing.value || snapshotRefreshing.value)
const cacheAgeLabel = computed(() => workspaceCacheAgeText(cacheSyncedAt.value))
const syncLabel = computed(() => {
  if (isSyncing.value) return hydratedFromCache.value ? '正在同步最新状态' : '正在刷新'
  if (hydratedFromCache.value && cacheAgeLabel.value) return `显示上次同步状态：${cacheAgeLabel.value}`
  return ''
})
const isWaitingHuman = computed(() => activeTask.value?.status === 'waiting_human')
const isPausedRun = computed(() => activeTask.value?.status === 'paused_for_review')
const isStartableTask = computed(() => startableStatuses.has(activeTask.value?.status))
const isRuntimeActive = computed(() => runtimeActiveStatuses.has(activeTask.value?.status))
const isRuntimeStateFromStaleCache = computed(() => (
  hydratedFromCache.value
  && isRuntimeActive.value
  && !isWorkspaceRuntimeCacheFresh(cacheSyncedAt.value)
))
const canContinueRun = computed(() => (
  (isStartableTask.value || isPausedRun.value) && !isWaitingHuman.value
))
const canPauseRun = computed(() => activeTaskId.value && pausableStatuses.has(activeTask.value?.status))
const runActionLabel = computed(() => (isStartableTask.value ? '启动运行' : '继续运行'))
const waitingStep = computed(() => steps.value.find((step) => step.status === 'waiting_human') || null)
const codexWorkspacePath = computed(() => taskRun.value?.codex?.workspace_path || activeTask.value?.codex_workspace_path || '')
const reportRoute = computed(() => {
  if (!activeTaskId.value) return null
  return activeTask.value?.status === 'completed'
    ? { path: `/tasks/${activeTaskId.value}`, query: { tab: 'report' } }
    : { path: `/tasks/${activeTaskId.value}` }
})
const isBootstrapping = computed(() => activeTask.value && isRuntimeActive.value && !finished.value && steps.value.length === 0)
const stepSummary = computed(() => steps.value.slice(0, 8))
const progressHeadline = computed(() => {
  if (!activeTask.value) return '还没有正在展示的实验'
  if (isRuntimeStateFromStaleCache.value) return '正在确认任务状态'
  if (isStartableTask.value) return '任务等待启动'
  if (isWaitingHuman.value) return '等待人工确认'
  if (isPausedRun.value) return '任务已暂停'
  if (isBootstrapping.value) return '正在创建环境'
  return finished.value ? '最近实验已结束' : `${modelDisplayName.value} 正在执行实验`
})
const progressDescription = computed(() => {
  if (!activeTask.value) return '开始任务后，工作台会自动展示当前进度和步骤目录。'
  if (isRuntimeStateFromStaleCache.value) return '这里先展示上次同步到的记录，正在向后端确认 Codex 是否仍有活动执行轮次。'
  if (isStartableTask.value) return '数据已准备好；只有点击启动运行后，后端才会向 Codex 提交任务并产生实时进度。'
  if (isWaitingHuman.value) return 'Codex 已暂停在人工确认节点，确认或调整方案后才会继续执行。'
  if (isPausedRun.value) return '当前运行已暂停，可以从现有工作区继续。'
  if (isBootstrapping.value) return `${modelDisplayName.value} 正在初始化运行环境和任务工作区，随后会显示数据分析进度。`
  return `工作台直接展示 ${modelDisplayName.value} 后端写入的运行步骤、状态和快速目录。`
})
const progressPercent = computed(() => {
  if (!activeTask.value) return 0
  return taskProgressPercent({
    status: activeTask.value?.status,
    steps: steps.value,
    isBootstrapping: isBootstrapping.value,
    progressPercent: taskRun.value?.progress_percent,
  })
})
const codexStream = createCodexRealtimeStream({
  state: codexRealtime,
  getSessionId: () => taskRun.value?.codex?.session_id || activeTask.value?.codex_session_id || '',
  getTaskId: () => activeTaskId.value,
  getSnapshotCodex: () => taskRun.value?.codex,
  isFinished: () => finished.value,
  onMessage: (payload) => {
    mergeRealtimeEvent(payload)
  },
  onError: (err) => {
    error.value = err.message
  },
})

function workspaceCacheContext() {
  const userId = getCachedUser()?.id
  const teamId = getActiveTeamHint()?.id
  return userId && teamId ? { userId, teamId } : null
}

function clearActiveWorkspace() {
  task.value = null
  taskRun.value = null
  steps.value = []
  resetCodexRealtimeState(codexRealtime.value)
  closeStream()
}

function persistWorkspaceCache() {
  const context = workspaceCacheContext()
  if (!context) return
  const now = Date.now()
  const written = writeWorkspaceCache(context, {
    tasks: tasks.value,
    activeTaskId: activeTaskId.value,
    task: task.value,
    taskRun: taskRun.value,
    steps: steps.value,
  }, now)
  if (written) cacheSyncedAt.value = now
}

function hydrateWorkspaceFromCache() {
  const cached = readWorkspaceCache(workspaceCacheContext())
  if (!cached) return false
  if (!runtimeActiveStatuses.has(cached.task?.status)) return false
  tasks.value = Array.isArray(cached.tasks) ? cached.tasks : []
  task.value = cached.task || null
  taskRun.value = cached.taskRun || null
  steps.value = Array.isArray(cached.steps) ? cached.steps : []
  cacheSyncedAt.value = cached.cachedAt
  hydratedFromCache.value = true
  resetCodexRealtimeState(codexRealtime.value)
  seedCodexRealtimeFromSnapshot(codexRealtime.value, taskRun.value?.codex)
  connectStream()
  return true
}

function patchActiveTask(patch) {
  if (!activeTaskId.value || !patch || typeof patch !== 'object') return
  const updatedAt = new Date().toISOString()
  task.value = {
    ...(task.value || {}),
    ...patch,
    updated_at: patch.updated_at || updatedAt,
  }
  tasks.value = tasks.value.map((item) => (
    taskIdOf(item) === activeTaskId.value ? { ...item, ...patch, updated_at: patch.updated_at || updatedAt } : item
  ))
}

function mergeRealtimeEvent(payload) {
  if (!payload || typeof payload !== 'object' || !activeTask.value) return
  if (!shouldApplyRealtimeTaskPatch(payload, codexRealtime.value.status)) return
  if (finished.value && payload.type !== 'task_completed') return

  if (payload.type === 'task_completed') {
    patchActiveTask({ status: 'completed', codex_status: 'completed' })
    taskRun.value = {
      ...(taskRun.value || {}),
      progress_percent: 100,
      progress_status: 'completed',
      codex: {
        ...(taskRun.value?.codex || {}),
        status: 'completed',
      },
    }
    persistWorkspaceCache()
    refreshSnapshot({ force: true })
    return
  }

  if (payload.type === 'plan_generation_completed') {
    patchActiveTask({ status: 'paused_for_review', codex_status: 'waiting_plan_approval' })
    persistWorkspaceCache()
    return
  }

  if (payload.type === 'quota_exhausted') {
    patchActiveTask({ status: 'paused_for_review', codex_status: 'interrupted', notes: payload.reason || activeTask.value?.notes })
    taskRun.value = {
      ...(taskRun.value || {}),
      progress_status: 'blocked',
      current_activity: payload.reason || taskRun.value?.current_activity || '',
      codex: {
        ...(taskRun.value?.codex || {}),
        status: 'interrupted',
      },
    }
    persistWorkspaceCache()
    closeStream()
    refreshSnapshot({ force: true })
    return
  }

  if (['task_resume_requested', 'modeling_started', 'turn_started'].includes(payload.type)) {
    patchActiveTask({ status: 'running', codex_status: 'running' })
    persistWorkspaceCache()
    return
  }

  if (payload.type === 'activity') {
    taskRun.value = {
      ...(taskRun.value || {}),
      current_activity: payload.message || taskRun.value?.current_activity || '',
      progress_status: payload.status || taskRun.value?.progress_status || '',
    }
    persistWorkspaceCache()
  }
}

function mergeSnapshot(data) {
  task.value = {
    ...(task.value || {}),
    ...data,
  }
  if (Array.isArray(data.steps)) steps.value = data.steps
}

async function loadTask(taskId, options = {}) {
  if (!taskId) {
    clearActiveWorkspace()
    persistWorkspaceCache()
    return
  }
  const detail = await getTaskRuntimeSnapshot(taskId, { sync: options.sync !== false })
  if (disposed) return
  const freshTask = detail.task || detail
  tasks.value = tasks.value.map((item) => (
    taskIdOf(item) === taskId
      ? {
          ...item,
          ...freshTask,
        }
      : item
  ))
  if (!runtimeActiveStatuses.has(freshTask?.status)) {
    clearActiveWorkspace()
    persistWorkspaceCache()
    return
  }
  task.value = {
    ...(task.value || {}),
    ...freshTask,
  }
  taskRun.value = detail.task_run || null
  if (Array.isArray(detail.task_run?.steps)) steps.value = detail.task_run.steps
  seedCodexRealtimeFromSnapshot(codexRealtime.value, taskRun.value?.codex)
  connectStream()
  hydratedFromCache.value = false
  persistWorkspaceCache()
}

async function load(options = {}) {
  const background = options.background === true || hasWorkspaceState.value
  if (background) refreshing.value = true
  else loading.value = true
  error.value = ''
  try {
    const data = await getMyTasks()
    if (disposed) return
    tasks.value = Array.isArray(data) ? data : []
    const selected = pickActiveTask(tasks.value)
    const selectedTaskId = taskIdOf(selected)
    if (selectedTaskId) {
      if (taskIdOf(task.value) !== selectedTaskId) {
        clearActiveWorkspace()
      }
      await loadTask(selectedTaskId, { sync: false })
      refreshSnapshot({ force: true })
    } else {
      clearActiveWorkspace()
      persistWorkspaceCache()
    }
    hydratedFromCache.value = false
  } catch (err) {
    error.value = err.message
  } finally {
    if (background) refreshing.value = false
    else loading.value = false
  }
}

function realtimeIsLive() {
  return ['connected', 'running', 'replaying'].includes(codexRealtime.value.status)
}

async function refreshSnapshot(options = {}) {
  if (
    loading.value
    || snapshotRefreshing.value
    || !activeTaskId.value
    || (finished.value && !options.force)
    || (!options.force && realtimeIsLive() && codexRealtime.value.events.length)
  ) return
  snapshotRefreshing.value = true
  try {
    await loadTask(activeTaskId.value)
  } catch (err) {
    error.value = err.message
  } finally {
    snapshotRefreshing.value = false
  }
}

function connectStream() {
  codexStream.connect()
}

function closeStream() {
  codexStream.close()
}

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function openDetail() {
  if (!activeTaskId.value) return
  await router.push(reportRoute.value || `/tasks/${activeTaskId.value}`)
}

async function openHitlApproval(step = null) {
  if (step && step.status !== 'waiting_human') return
  if (!activeTaskId.value) return
  error.value = ''
  try {
    hitl.value = await getHitl(activeTaskId.value)
    hitlModalOpen.value = true
  } catch (err) {
    error.value = err.message
  }
}

async function continueRun() {
  if (!activeTaskId.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await rerunTask(activeTaskId.value, {}, continueRunOptions(activeTask.value, taskRun.value))
    if (task.value) task.value = { ...task.value, ...(data || {}) }
    persistWorkspaceCache()
    await loadTask(activeTaskId.value)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function pauseCurrentRun() {
  const taskId = activeTaskId.value
  if (!taskId || pausing.value) return
  const confirmed = window.confirm('确定要暂停当前任务吗？Codex 会中断当前轮次，之后可以从当前工作区继续运行。')
  if (!confirmed) return
  pausing.value = true
  error.value = ''
  try {
    const pausedTask = await pauseTask(taskId)
    if (task.value) task.value = { ...task.value, ...(pausedTask || {}) }
    tasks.value = tasks.value.map((item) => (
      taskIdOf(item) === taskId ? { ...item, ...(pausedTask || {}) } : item
    ))
    persistWorkspaceCache()
    closeStream()
    await loadTask(taskId)
  } catch (err) {
    error.value = err.message
  } finally {
    pausing.value = false
  }
}

async function handleHitlSubmitted(data) {
  const taskId = activeTaskId.value
  hitlModalOpen.value = false
  hitl.value = null
  if (data?.status && task.value) {
    task.value = { ...task.value, status: data.status, error: null }
    tasks.value = tasks.value.map((item) => (
      taskIdOf(item) === taskId ? { ...item, status: data.status, error: null } : item
    ))
    persistWorkspaceCache()
  }
  connectStream()
  try {
    await loadTask(taskId)
  } catch (err) {
    error.value = err.message
  }
}

onMounted(() => {
  hydrateWorkspaceFromCache()
  load({ background: hasWorkspaceState.value })
  pollTimer = window.setInterval(refreshSnapshot, SNAPSHOT_POLL_MS)
})
onUnmounted(() => {
  disposed = true
  closeStream()
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <PageHeader title="工作台" :description="`展示当前实验进度、${modelDisplayName} 运行步骤和快速目录。`">
    <template #actions>
      <button class="secondary-action refresh-action" type="button" :disabled="loading || refreshing" @click="load({ background: hasWorkspaceState })">
        <RefreshCw :class="{ spinning: loading || isSyncing }" :size="18" />刷新
      </button>
      <button v-if="canPauseRun" class="secondary-action" type="button" :disabled="loading || pausing" @click="pauseCurrentRun">
        <XCircle :size="18" />{{ pausing ? '暂停中' : '暂停运行' }}
      </button>
      <button v-if="canContinueRun" class="secondary-action" type="button" :disabled="loading" @click="continueRun">
        <ArrowRight :size="18" />{{ runActionLabel }}
      </button>
      <RouterLink class="primary-action" to="/create"><FilePlus2 :size="18" />开始任务</RouterLink>
    </template>
  </PageHeader>

  <TaskFlowSteps :current-step="3" />

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="syncLabel" class="workspace-sync-note">
    <RefreshCw v-if="isSyncing" class="spinning" :size="14" />
    <span>{{ syncLabel }}</span>
  </p>

  <LoadingBlock v-if="loading && !hasWorkspaceState" />

  <EmptyState v-else-if="!activeTask" title="暂无进行中的实验" description="工作台只展示当前进行中的任务；历史任务可在任务中心只读查看。" />

  <div v-else class="task-progress-layout">
    <main class="task-progress-main">
      <section id="progress-overview" class="panel progress-panel">
        <div class="progress-head">
          <div>
            <p class="eyebrow">当前实验</p>
            <h2>{{ displayTaskTitle(activeTask, '实验进度') }}</h2>
            <p class="muted">{{ progressHeadline }}。{{ progressDescription }}</p>
          </div>
          <StatusBadge v-if="activeTask?.status" :status="activeTask.status" />
        </div>
        <div class="simple-progress">
          <span :style="{ width: `${progressPercent}%` }"></span>
        </div>
        <div class="progress-meta">
          <strong>{{ progressPercent }}%</strong>
          <span>{{ activeTask?.status || '加载中' }}</span>
        </div>
        <p v-if="codexWorkspacePath" class="muted codex-workspace-path">{{ modelDisplayName }} workspace: {{ codexWorkspacePath }}</p>
        <div v-if="finished" class="report-ready-card">
          <div>
            <strong>{{ activeTask?.status === 'completed' ? '运行报告已生成' : '运行已结束' }}</strong>
            <span>{{ activeTask?.status === 'completed' ? '查看本次实验的运行报告、源码和预测演示。' : '查看本次实验的状态、日志和已生成内容。' }}</span>
          </div>
          <RouterLink class="primary-action" :to="reportRoute">
            <FileText :size="18" />
            {{ activeTask?.status === 'completed' ? '查看运行报告' : '查看任务详情' }}
          </RouterLink>
        </div>
        <div v-if="isWaitingHuman" class="form-warning progress-alert">
          <span>当前任务正在等待人工确认。</span>
          <button class="primary-action compact-action" type="button" @click="openHitlApproval(waitingStep)">
            处理人工确认
          </button>
        </div>
      </section>

      <section id="agent-steps" class="panel">
        <div class="panel-title"><span>{{ modelDisplayName }} 运行步骤</span></div>
        <div v-if="isRuntimeStateFromStaleCache" class="startup-board">
          <div class="startup-node active"><span></span><strong>正在确认最新状态</strong></div>
          <div class="startup-node"><span></span><strong>等待后端校验运行轮次</strong></div>
          <div class="startup-node"><span></span><strong>同步任务记录</strong></div>
          <div class="startup-node"><span></span><strong>更新工作台展示</strong></div>
        </div>
        <div v-else-if="isStartableTask" class="startup-board">
          <div class="startup-node active"><span></span><strong>数据已准备</strong></div>
          <div class="startup-node"><span></span><strong>等待启动运行</strong></div>
          <div class="startup-node"><span></span><strong>提交给 {{ modelDisplayName }}</strong></div>
          <div class="startup-node"><span></span><strong>生成工作计划</strong></div>
        </div>
        <div v-else-if="isBootstrapping" class="startup-board">
          <div class="startup-node active"><span></span><strong>正在创建环境</strong></div>
          <div class="startup-node"><span></span><strong>正在分析数据集</strong></div>
          <div class="startup-node"><span></span><strong>生成工作计划</strong></div>
          <div class="startup-node"><span></span><strong>等待人工确认</strong></div>
        </div>
        <TaskTimeline v-else :steps="steps" :interactive-hitl="isWaitingHuman" @hitl-request="openHitlApproval" />
      </section>

      <CodexRealtimePanel
        :events="codexRealtime.events"
        :status="codexRealtime.status"
        :activity="codexRealtime.activity"
      />
    </main>

    <aside class="panel task-side-nav">
      <div class="panel-title"><span><Compass :size="18" /> 快速定位</span></div>
      <button type="button" @click="scrollToSection('progress-overview')">
        <Settings2 :size="18" />
        <span>流程概览</span>
      </button>
      <button type="button" @click="scrollToSection('agent-steps')">
        <Workflow :size="18" />
        <span>{{ modelDisplayName }} 步骤</span>
      </button>
      <button type="button" @click="scrollToSection('codex-realtime')">
        <Settings2 :size="18" />
        <span>实时运行</span>
      </button>
      <button type="button" @click="openDetail">
        <ArrowRight :size="18" />
        <span>任务详情</span>
      </button>
      <button v-if="isWaitingHuman" class="urgent" type="button" @click="openHitlApproval(waitingStep)">
        <ArrowRight :size="18" />
        <span>处理人工确认</span>
      </button>
      <RouterLink v-if="finished" class="side-report-link" :to="reportRoute">
        <FileText :size="18" />
        <span>{{ activeTask?.status === 'completed' ? '运行报告' : '结束详情' }}</span>
      </RouterLink>

      <div class="side-step-list">
        <strong>步骤目录</strong>
        <button
          v-for="(step, index) in stepSummary"
          :key="step.id || `${step.name || step.node || 'step'}-${index}`"
          type="button"
          :class="step.status"
          @click="scrollToSection('agent-steps')"
        >
          <span>{{ step.agent_role || step.title || step.name || step.node || `步骤${index + 1}` }}</span>
          <small>{{ stepStatusLabel(step.status) }}</small>
        </button>
        <p v-if="isBootstrapping" class="muted">正在生成步骤目录</p>
      </div>
    </aside>
  </div>

  <HitlApprovalModal
    :open="hitlModalOpen"
    :task-id="activeTaskId"
    :hitl="hitl"
    @close="hitlModalOpen = false"
    @submitted="handleHitlSubmitted"
  />
</template>
