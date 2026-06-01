<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, CheckCircle2, Compass, FilePlus2, RefreshCw, Settings2, Workflow, XCircle } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import CodexRealtimePanel from '@/components/CodexRealtimePanel.vue'
import HitlApprovalModal from '@/components/HitlApprovalModal.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TaskFlowSteps from '@/components/TaskFlowSteps.vue'
import TaskTimeline from '@/components/TaskTimeline.vue'
import { getHitl, getTaskRuntimeSnapshot, pauseTask, rerunTask } from '@/api/client'
import { createCodexRealtimeStream } from '@/composables/useCodexRealtimeStream'
import { displayTaskTitle } from '@/utils/labels'
import { createCodexRealtimeState, seedCodexRealtimeFromSnapshot } from '@/utils/codexRealtime'
import { modelDisplayName } from '@/utils/modelProfile'
import { taskProgressPercent } from '@/utils/progress'
import { continueRunOptions } from '@/utils/taskRunControl'
import { firstWaitingHumanStep, hasPendingHumanConfirmation, isHumanWaitingStatus } from '@/utils/taskHumanState'
import { isFinishedTaskStatus, stepStatusLabel } from '@/utils/taskRecords'

const props = defineProps({ taskId: { type: String, required: true } })
const router = useRouter()
const task = ref(null)
const taskRun = ref(null)
const steps = ref([])
const codexRealtime = ref(createCodexRealtimeState())
const error = ref('')
const loading = ref(false)
const pausing = ref(false)
const hitl = ref(null)
const hitlModalOpen = ref(false)
let pollTimer = null
const pausableStatuses = new Set(['running'])
const runtimeActiveStatuses = new Set(['running'])
const startableStatuses = new Set(['uploaded', 'planning'])

const finished = computed(() => isFinishedTaskStatus(task.value?.status))
const canPauseRun = computed(() => pausableStatuses.has(task.value?.status))
const isStartableTask = computed(() => startableStatuses.has(task.value?.status))
const isRuntimeActive = computed(() => runtimeActiveStatuses.has(task.value?.status))
const runActionLabel = computed(() => (isStartableTask.value ? '启动运行' : '继续运行'))
const waitingStep = computed(() => firstWaitingHumanStep(steps.value))
const isWaitingHuman = computed(() => hasPendingHumanConfirmation(task.value, taskRun.value, steps.value))
const canContinueRun = computed(() => (task.value?.status === 'paused_for_review' || isStartableTask.value) && !isWaitingHuman.value)
const isBootstrapping = computed(() => isRuntimeActive.value && !finished.value && steps.value.length === 0)
const stepSummary = computed(() => steps.value.slice(0, 8))
const codexWorkspacePath = computed(() => taskRun.value?.codex?.workspace_path || task.value?.codex_workspace_path || '')
const progressHeadline = computed(() => {
  if (isStartableTask.value) return '任务等待启动'
  if (isWaitingHuman.value) return '等待人工确认'
  if (task.value?.status === 'paused_for_review') return '已暂停'
  if (isBootstrapping.value) return '正在创建环境'
  return finished.value ? '执行已暂停或结束' : `${modelDisplayName.value} 正在执行任务`
})

const progressDescription = computed(() => {
  if (isStartableTask.value) return `数据已准备好；点击启动运行后才会提交给 ${modelDisplayName.value}。`
  if (isWaitingHuman.value) return `${modelDisplayName.value} 已完成当前阶段规划，需要进入任务详情确认、调整或拒绝后继续执行。`
  if (task.value?.status === 'paused_for_review') return `当前 ${modelDisplayName.value} 运行已暂停，可以继续同一个任务工作区。`
  if (isBootstrapping.value) return `${modelDisplayName.value} 正在初始化运行环境和任务工作区，随后会显示数据分析和计划生成进度。`
  return `此页直接展示 ${modelDisplayName.value} 后端写入的运行步骤和状态，报告、源码和演示请在任务完成后进入详情页查看。`
})
const progressPercent = computed(() => {
  return taskProgressPercent({
    status: task.value?.status,
    steps: steps.value,
    isBootstrapping: isBootstrapping.value,
    progressPercent: taskRun.value?.progress_percent,
  })
})
const codexStream = createCodexRealtimeStream({
  state: codexRealtime,
  getSessionId: () => taskRun.value?.codex?.session_id || task.value?.codex_session_id || '',
  getTaskId: () => props.taskId,
  getSnapshotCodex: () => taskRun.value?.codex,
  isFinished: () => finished.value,
  onError: (err) => {
    error.value = err.message
  },
})

function mergeSnapshot(data) {
  task.value = {
    ...(task.value || {}),
    ...data,
  }
  if (Array.isArray(data.steps)) steps.value = data.steps
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const detail = await getTaskRuntimeSnapshot(props.taskId)
    task.value = detail.task || detail
    taskRun.value = detail.task_run || null
    steps.value = detail.task_run?.steps || []
    seedCodexRealtimeFromSnapshot(codexRealtime.value, taskRun.value?.codex)
    connectStream()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function refreshSnapshot() {
  if (loading.value || finished.value) return
  try {
    const detail = await getTaskRuntimeSnapshot(props.taskId)
    task.value = detail.task || detail
    taskRun.value = detail.task_run || taskRun.value
    steps.value = detail.task_run?.steps || steps.value
    seedCodexRealtimeFromSnapshot(codexRealtime.value, taskRun.value?.codex)
    connectStream()
  } catch (err) {
    error.value = err.message
  }
}

async function openDetail() {
  const target = { path: `/tasks/${props.taskId}` }
  try {
    await router.push(target)
  } catch {
    window.location.assign(`/tasks/${props.taskId}`)
  }
}

async function openHitlApproval(step = null) {
  if (step && !isHumanWaitingStatus(step.status)) return
  error.value = ''
  try {
    hitl.value = await getHitl(props.taskId)
    hitlModalOpen.value = true
  } catch (err) {
    error.value = err.message
  }
}

function scrollToSection(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function openCurrentHitl() {
  await openHitlApproval(waitingStep.value)
}

async function pauseCurrentRun() {
  if (pausing.value || !canPauseRun.value) return
  const confirmed = window.confirm('确定要暂停当前任务吗？Codex 会中断当前轮次，之后可以从当前工作区继续运行。')
  if (!confirmed) return
  pausing.value = true
  error.value = ''
  try {
    const pausedTask = await pauseTask(props.taskId)
    if (task.value) task.value = { ...task.value, ...(pausedTask || {}) }
    closeStream()
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    pausing.value = false
  }
}

async function continueRun() {
  if (!props.taskId || loading.value || !canContinueRun.value) return
  loading.value = true
  error.value = ''
  try {
    const data = await rerunTask(props.taskId, {}, continueRunOptions(task.value, taskRun.value))
    if (task.value) task.value = { ...task.value, ...(data || {}) }
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function handleHitlSubmitted(data) {
  hitlModalOpen.value = false
  hitl.value = null
  if (data?.status && task.value) {
    task.value = { ...task.value, status: data.status, error: null }
  }
  connectStream()
  await refreshSnapshot()
}

function connectStream() {
  codexStream.connect()
}

function closeStream() {
  codexStream.close()
}

onMounted(async () => {
  await load()
  pollTimer = window.setInterval(refreshSnapshot, 2500)
})
onUnmounted(() => {
  closeStream()
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>

<template>
  <PageHeader :title="displayTaskTitle(task, '任务执行进度')" :description="taskId">
    <template #actions>
      <button class="secondary-action refresh-action" type="button" :disabled="loading" @click="load">
        <RefreshCw :class="{ spinning: loading }" :size="18" />刷新
      </button>
      <button v-if="canPauseRun" class="secondary-action" type="button" :disabled="loading || pausing" @click="pauseCurrentRun">
        <XCircle :size="18" />{{ pausing ? '暂停中' : '暂停运行' }}
      </button>
      <button v-if="canContinueRun" class="secondary-action" type="button" :disabled="loading" @click="continueRun">
        <ArrowRight :size="18" />{{ runActionLabel }}
      </button>
      <button class="primary-action" type="button" @click="openDetail">
        查看详情 <ArrowRight :size="18" />
      </button>
    </template>
  </PageHeader>

  <TaskFlowSteps :current-step="3" />

  <p v-if="error" class="form-error">{{ error }}</p>

  <LoadingBlock v-if="loading" />

  <div v-else class="task-progress-layout">
    <main class="task-progress-main">
      <section id="progress-overview" class="panel progress-panel">
        <div class="progress-head">
          <div>
            <p class="eyebrow">流程进度</p>
            <h2>{{ progressHeadline }}</h2>
            <p class="muted">{{ progressDescription }}</p>
          </div>
          <StatusBadge v-if="task?.status" :status="task.status" />
        </div>
        <div v-if="isWaitingHuman" class="form-warning progress-alert">
          <CheckCircle2 :size="16" />
          <span>当前任务已暂停在人工确认节点。</span>
          <button class="primary-action compact-action" type="button" @click="openCurrentHitl">处理确认</button>
        </div>
        <div class="simple-progress">
          <span :style="{ width: `${progressPercent}%` }"></span>
        </div>
        <div class="progress-meta">
          <strong>{{ progressPercent }}%</strong>
          <span>{{ task?.status || '加载中' }}</span>
        </div>
        <p v-if="codexWorkspacePath" class="muted codex-workspace-path">{{ modelDisplayName }} workspace: {{ codexWorkspacePath }}</p>
      </section>

      <section id="agent-steps" class="panel">
        <div class="panel-title"><span>{{ modelDisplayName }} 运行步骤</span></div>
        <div v-if="isBootstrapping" class="startup-board">
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
      <button v-if="isWaitingHuman" class="urgent" type="button" @click="openCurrentHitl">
        <CheckCircle2 :size="18" />
        <span>处理人工确认</span>
      </button>
      <button type="button" @click="openDetail">
        <FilePlus2 :size="18" />
        <span>任务详情</span>
      </button>

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
    :task-id="taskId"
    :hitl="hitl"
    @close="hitlModalOpen = false"
    @submitted="handleHitlSubmitted"
  />
</template>
