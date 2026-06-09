<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CheckCircle2, Play, RefreshCw, Save, Send, Trash2, X } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import HitlApprovalModal from '@/components/HitlApprovalModal.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import MetricCard from '@/components/MetricCard.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import TaskFlowSteps from '@/components/TaskFlowSteps.vue'
import TaskOverviewPanel from '@/components/TaskOverviewPanel.vue'
import TaskPredictionPanel from '@/components/TaskPredictionPanel.vue'
import { displayTaskTitle, taskStatusLabel, taskTypeLabel } from '@/utils/labels'
import { formatPredictionValue, formatTokenCount } from '@/utils/formatters'
import {
  buildTokenComparison,
  buildTokenObservability,
  demoRowsFromDelivery,
  hasObjectContent,
  normalizeTokenUsage,
  predictionValueFromPayload,
  reportDepthLabel,
  searchDepthLabel,
  strategyLabel,
  valueOrDash,
} from '@/utils/taskDetail'
import {
  deleteTask,
  getCodexPlan,
  getMyTasks,
  getReport,
  getTaskRuntimeSnapshot,
  getWorkspaceTasks,
  pauseTask,
  rerunTask,
} from '@/api/tasks'
import { publishPlan, publishPrompt } from '@/api/community'
import { getOperationCode, updateOperationCode, validateOperationCode } from '@/api/taskCodeArtifacts'
import { getHitl } from '@/api/taskHuman'
import { getDelivery, predict } from '@/api/taskPredictionDemo'
import { useTaskDetailOverview } from '@/composables/useTaskDetailOverview'
import { createCodexRealtimeStream } from '@/composables/useCodexRealtimeStream'
import { optionalLoad } from '@/utils/async'
import { createCodexRealtimeState, seedCodexRealtimeFromSnapshot } from '@/utils/codexRealtime'
import { modelDisplayName } from '@/utils/modelProfile'
import { continueRunOptions } from '@/utils/taskRunControl'
import { firstWaitingHumanStep, hasPendingHumanConfirmation, isHumanWaitingStatus } from '@/utils/taskHumanState'
import { isFinishedTaskStatus, pickBlockingRuntimeTask, taskIdOf } from '@/utils/taskRecords'

const props = defineProps({ taskId: { type: String, required: true } })
const route = useRoute()
const router = useRouter()
const initialTab = String(route.query.tab || '')
const validTabs = new Set(['overview', 'report', 'demo', 'code', 'publish'])
const detailSections = [
  { value: 'overview', label: '概览' },
  { value: 'report', label: '报告' },
  { value: 'demo', label: '预测' },
  { value: 'code', label: '源码' },
  { value: 'publish', label: '发布' },
]
const task = ref(null)
const taskRun = ref(null)
const steps = ref([])
const codexRealtime = ref(createCodexRealtimeState())
const metrics = ref(null)
const importance = ref(null)
const overview = ref(null)
const report = ref('')
const code = ref('')
const codeEditable = ref(false)
const codeLoadDetail = ref('')
const delivery = ref(null)
const hitl = ref(null)
const peerTasks = ref([])
const codeValidation = ref(null)
const activeTab = ref(validTabs.has(initialTab) ? initialTab : 'overview')
const loading = ref(false)
const sectionLoading = ref(false)
const error = ref('')
const message = ref('')
const hitlModalOpen = ref(false)
const hitlLoading = ref(false)
const hitlLoadError = ref('')
const predictionResult = ref(null)
const predictionError = ref('')
const predictionLoading = ref(false)
const promptName = ref('')
const promptDescription = ref('')
const planName = ref('')
const planDescription = ref('')
const planText = ref('')
const planEditorOpen = ref(false)
const loadedSections = ref({ overview: false, report: false, demo: false, code: false, publish: false })
const activeTaskId = ref('')
let snapshotRefreshTimer = null
let peerTaskLoadVersion = 0
const runtimeActiveStatuses = new Set(['running'])
const startableStatuses = new Set(['uploaded', 'planning'])
const reportFetchStatuses = new Set(['completed', 'failed', 'published'])

const isCurrentActiveTask = computed(() => activeTaskId.value && activeTaskId.value === props.taskId)
const hasAnotherActiveTask = computed(() => activeTaskId.value && activeTaskId.value !== props.taskId)
const readOnlyMode = computed(() => Boolean(hasAnotherActiveTask.value))
const isFinished = computed(() => isFinishedTaskStatus(task.value?.status))
const isRuntimeActive = computed(() => runtimeActiveStatuses.has(task.value?.status))
const canControlTask = computed(() => !readOnlyMode.value && !isFinished.value)
const isLiveCodexRun = computed(() => isCurrentActiveTask.value && !isFinished.value && isRuntimeActive.value)
const hasCodexSnapshotSteps = computed(() => Array.isArray(taskRun.value?.codex?.steps) && taskRun.value.codex.steps.length > 0)
const shouldConnectRealtime = computed(() => isLiveCodexRun.value)
const showRealtime = computed(() => isLiveCodexRun.value || hasCodexSnapshotSteps.value || codexRealtime.value.events.length > 0)
const pausable = computed(() => isCurrentActiveTask.value && task.value?.status === 'running')
const waitingStep = computed(() => firstWaitingHumanStep(steps.value))
const isWaitingHuman = computed(() => hasPendingHumanConfirmation(task.value, taskRun.value, steps.value))
const canContinueRun = computed(() => (
  canControlTask.value
  && ['planning', 'uploaded', 'paused_for_review'].includes(task.value?.status)
  && !isWaitingHuman.value
))
const runActionLabel = computed(() => (startableStatuses.has(task.value?.status) ? '启动运行' : '继续运行'))
const canHandleHitl = computed(() => canControlTask.value && isWaitingHuman.value)
const canEditCode = computed(() => !readOnlyMode.value && codeEditable.value)
const codexRunStrategy = computed(() => taskRun.value?.codex?.run_strategy || null)
const strategyExecutionLimits = computed(() => codexRunStrategy.value?.execution_limits || {})
const strategyOverview = computed(() => {
  const strategy = codexRunStrategy.value
  if (!strategy || typeof strategy !== 'object') return null
  const limits = strategy.execution_limits || {}
  return {
    id: strategy.strategy_id || '',
    label: strategyLabel(strategy.strategy_id),
    reason: strategy.decision_reason || '当前策略文件没有提供选择原因。',
    items: [
      { label: '候选模型数', value: valueOrDash(limits.candidate_model_count) },
      { label: 'Subagents', value: limits.allow_subagents ? '允许' : '不启用' },
      { label: '调参深度', value: searchDepthLabel(limits.hyperparameter_search) },
      { label: '报告深度', value: reportDepthLabel(limits.report_depth) },
      { label: '自动改进轮数', value: valueOrDash(limits.max_auto_improvement_rounds) },
      { label: '顾问触发轮数', value: valueOrDash(limits.advisor_after_failed_rounds) },
    ],
  }
})
const codexTokenUsage = computed(() => (
  normalizeTokenUsage(taskRun.value?.codex?.token_usage)
  || normalizeTokenUsage(task.value?.llm_usage)
  || null
))
const llmUsageText = computed(() => formatTokenCount(codexTokenUsage.value?.total_tokens))
const tokenComparison = computed(() => buildTokenComparison(codexTokenUsage.value, peerTasks.value, task.value))
const tokenObservability = computed(() => buildTokenObservability({
  usage: codexTokenUsage.value || {},
  limits: strategyExecutionLimits.value,
  threadId: taskRun.value?.codex?.thread_id,
  comparison: tokenComparison.value,
}))
const taskFlowStep = computed(() => {
  if (task.value?.status === 'completed') return 4
  if (['running', 'waiting_human', 'paused_for_review', 'failed', 'cancelled'].includes(task.value?.status)) return 3
  return 2
})
const {
  effectiveOverview,
  targetSummaries,
  renderedReport,
  planPreview,
  primaryMetric,
  overviewConclusion,
  overviewCheckItems,
  overviewBadges,
  overviewFactors,
  overviewFactorDescription,
} = useTaskDetailOverview({ task, taskRun, metrics, importance, overview, report, planText })
const codexStream = createCodexRealtimeStream({
  state: codexRealtime,
  getSessionId: () => taskRun.value?.codex?.session_id || task.value?.codex_session_id || '',
  getTaskId: () => props.taskId,
  getSnapshotCodex: () => taskRun.value?.codex,
  isFinished: () => isFinished.value,
  allowFinishedReplay: true,
  onMessage: (payload) => {
    if (['token_usage_updated', 'task_completed', 'quota_exhausted'].includes(payload.type)) {
      scheduleSnapshotRefresh()
    }
  },
  onError: (err) => {
    error.value = err.message
  },
})
const predictionTargetName = computed(() => {
  if (Array.isArray(task.value?.target_columns) && task.value.target_columns.length) return task.value.target_columns.join('、')
  return task.value?.label_column || task.value?.target_column || effectiveOverview.value?.task_summary?.target || '预测值'
})
const predictionResultLabel = computed(() => predictionResult.value?.label || predictionTargetName.value)
const predictionResultValue = computed(() => {
  if (!predictionResult.value) return ''
  return formatPredictionValue(predictionResult.value.value)
})
const predictionResultNote = computed(() => predictionResult.value?.detail || '已使用当前任务生成的真实预测入口完成计算。')
const predictionStatusText = computed(() => {
  if (predictionLoading.value) return '预测中'
  if (predictionError.value) return '预测失败'
  if (predictionResult.value) return '已返回'
  return '等待运行'
})

function readPlanTextFromDetail(detail) {
  return detail?.task_run?.codex?.plan_text || detail?.codex?.plan_text || ''
}

function syncPlanTextFromDetail(detail, { overwrite = false } = {}) {
  const nextPlanText = readPlanTextFromDetail(detail)
  if (nextPlanText && (overwrite || !planText.value.trim())) {
    planText.value = nextPlanText
  }
}

function reconcileActiveTaskAfterSnapshot() {
  if (activeTaskId.value === props.taskId && !isRuntimeActive.value) {
    activeTaskId.value = ''
    closeStream()
  }
}

function hasGeneratedReportCandidate() {
  return Boolean(
    report.value.trim()
    || reportFetchStatuses.has(task.value?.status)
    || task.value?.last_run
    || taskRun.value?.artifacts?.has_run_summary
    || taskRun.value?.codex?.status === 'completed',
  )
}

async function refreshPlanText({ overwrite = false, sync = false } = {}) {
  if (sync) {
    const plan = await getCodexPlan(props.taskId)
    if (plan?.plan_text && (overwrite || !planText.value.trim())) {
      planText.value = plan.plan_text
    }
    return planText.value
  }
  const detail = await getTaskRuntimeSnapshot(props.taskId, { sync })
  if (detail.task) task.value = detail.task
  if (detail.task_run) taskRun.value = detail.task_run
  syncPlanTextFromDetail(detail, { overwrite })
  return planText.value
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [runtimeTasks, detail] = await Promise.all([
      optionalLoad(() => getWorkspaceTasks(), []),
      getTaskRuntimeSnapshot(props.taskId, { sync: false, taskDetail: 'summary' }),
    ])
    const currentActiveTask = pickBlockingRuntimeTask(runtimeTasks)
    activeTaskId.value = taskIdOf(currentActiveTask)
    if (!peerTasks.value.length && Array.isArray(runtimeTasks)) peerTasks.value = runtimeTasks
    task.value = detail.task || detail
    taskRun.value = detail.task_run || null
    reconcileActiveTaskAfterSnapshot()
    seedCodexRealtimeFromSnapshot(codexRealtime.value, taskRun.value?.codex)
    if (hasObjectContent(taskRun.value?.overview)) overview.value = taskRun.value.overview
    steps.value = taskRun.value?.steps || []
    metrics.value = taskRun.value?.metrics ? { values: taskRun.value.metrics } : metrics.value
    promptName.value = displayTaskTitle(task.value, `提示词 ${props.taskId.slice(0, 8)}`)
    promptDescription.value = task.value.requirement || task.value.description || ''
    planName.value = `${displayTaskTitle(task.value, '自动建模实验')} 执行方案`
    planDescription.value = report.value.slice(0, 180)
    syncPlanTextFromDetail(detail, { overwrite: true })
    loadedSections.value.overview = true
    ensureActiveTabLoaded({ silent: true })
    if (shouldConnectRealtime.value) connectStream()
    else closeStream()
    scheduleSnapshotRefresh()
    loadPeerTasksInBackground()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function refreshRuntimeSnapshot(options = {}) {
  const detail = await getTaskRuntimeSnapshot(props.taskId, { sync: options.sync === true, taskDetail: 'summary' })
  task.value = detail.task || detail
  taskRun.value = detail.task_run || taskRun.value
  reconcileActiveTaskAfterSnapshot()
  seedCodexRealtimeFromSnapshot(codexRealtime.value, taskRun.value?.codex)
  syncPlanTextFromDetail(detail)
  if (hasObjectContent(detail.task_run?.overview)) overview.value = detail.task_run.overview
  steps.value = detail.task_run?.steps || steps.value
  if (detail.task_run?.metrics) metrics.value = { values: detail.task_run.metrics }
  if (shouldConnectRealtime.value) connectStream()
  else closeStream()
}

async function loadPeerTasksInBackground() {
  const version = ++peerTaskLoadVersion
  try {
    const taskList = await optionalLoad(() => getMyTasks(), peerTasks.value)
    if (version !== peerTaskLoadVersion) return
    peerTasks.value = Array.isArray(taskList) ? taskList : []
  } catch {
    // Peer tasks only power comparison hints; the detail page must stay interactive without them.
  }
}

async function loadOverviewDetails() {
  loadedSections.value.overview = true
}

async function loadReportSection() {
  if (loadedSections.value.report) return
  if (!hasGeneratedReportCandidate()) {
    report.value = ''
    loadedSections.value.report = true
    return
  }
  const reportData = await optionalLoad(() => getReport(props.taskId), { content: '' })
  report.value = reportData.content || ''
  loadedSections.value.report = true
}

async function loadDemoSection() {
  if (loadedSections.value.demo) return
  const deliveryData = await optionalLoad(() => getDelivery(props.taskId))
  delivery.value = deliveryData
  loadedSections.value.demo = true
}

async function loadCodeSection() {
  if (loadedSections.value.code) return
  const codeData = await optionalLoad(() => getOperationCode(props.taskId), {
    content: '',
    editable: false,
    detail: '当前任务还没有可编辑源码。',
  })
  code.value = codeData.content || ''
  codeEditable.value = Boolean(codeData.editable)
  codeLoadDetail.value = codeData.detail || ''
  loadedSections.value.code = true
}

function codeActionBlockedMessage(actionName) {
  if (readOnlyMode.value) return `当前有其他任务正在进行，历史任务不能${actionName}源码。`
  return codeLoadDetail.value || '当前任务还没有可编辑源码。'
}

async function loadPublishSection() {
  if (loadedSections.value.publish) return
  const reportPromise = hasGeneratedReportCandidate()
    ? optionalLoad(() => getReport(props.taskId), { content: '' })
    : Promise.resolve({ content: '' })
  const [reportData] = await Promise.all([
    reportPromise,
    refreshPlanText().catch(() => planText.value),
  ])
  if (reportData?.content && !planDescription.value.trim()) planDescription.value = reportData.content.slice(0, 180)
  loadedSections.value.publish = true
}

async function ensureSectionLoaded(tab, options = {}) {
  const silent = options.silent === true
  if (!silent) sectionLoading.value = true
  error.value = ''
  try {
    if (tab === 'overview') await loadOverviewDetails()
    else if (tab === 'report') await loadReportSection()
    else if (tab === 'demo') await loadDemoSection()
    else if (tab === 'code') await loadCodeSection()
    else if (tab === 'publish') await loadPublishSection()
  } catch (err) {
    error.value = err.message
  } finally {
    if (!silent) sectionLoading.value = false
  }
}

function setActiveTab(tab) {
  if (!validTabs.has(tab)) return
  activeTab.value = tab
  ensureSectionLoaded(tab)
}

function ensureActiveTabLoaded(options = {}) {
  ensureSectionLoaded(activeTab.value, options)
}

async function runPredict(rows = null) {
  predictionError.value = ''
  if (readOnlyMode.value) {
    predictionResult.value = null
    predictionError.value = '当前有其他任务正在进行，历史任务暂不触发预测请求。'
    return
  }
  predictionResult.value = null
  predictionLoading.value = true
  try {
    const data = await predict(props.taskId, rows)
    const parsed = predictionValueFromPayload(data, {
      targetName: predictionTargetName.value,
      requiredFeatures: delivery.value?.required_features || [],
    })
    if (!parsed) throw new Error('预测接口已返回，但没有找到可展示的预测值。')
    predictionResult.value = {
      label: parsed.label || predictionTargetName.value,
      value: parsed.value,
      detail: data?.detail || '',
    }
  } catch (err) {
    predictionResult.value = null
    predictionError.value = err.message
  } finally {
    predictionLoading.value = false
  }
}

async function saveCode() {
  if (!canEditCode.value) {
    error.value = codeActionBlockedMessage('保存')
    return
  }
  try {
    await updateOperationCode(props.taskId, code.value)
    message.value = '源码已保存并通过语法检查'
  } catch (err) {
    error.value = err.message
  }
}

async function validateCode() {
  if (!canEditCode.value) {
    error.value = codeActionBlockedMessage('验证')
    return
  }
  try {
    codeValidation.value = await validateOperationCode(props.taskId)
    message.value = codeValidation.value.valid ? '源码验证通过' : '源码验证未通过'
  } catch (err) {
    error.value = err.message
  }
}

async function publishTaskPrompt() {
  if (readOnlyMode.value) {
    error.value = '当前有其他任务正在进行，历史任务暂不提交发布。'
    return
  }
  try {
    await publishPrompt(props.taskId, {
      name: promptName.value,
      description: promptDescription.value,
      task_category: task.value?.task_type || task.value?.problem_type || '',
      target_column: task.value?.target_column || '',
      metric: task.value?.metric || '',
    })
    message.value = '提示词已提交审核，管理员通过后会出现在社区广场。'
  } catch (err) {
    error.value = err.message
  }
}

async function publishTaskPlan() {
  if (readOnlyMode.value) {
    error.value = '当前有其他任务正在进行，历史任务暂不提交发布。'
    return
  }
  try {
    if (!planText.value.trim()) await refreshPlanText({ sync: true })
    if (!planText.value.trim()) throw new Error(`当前任务还没有可发布的 ${modelDisplayName.value} 执行方案。`)
    await publishPlan(props.taskId, {
      name: planName.value,
      description: planDescription.value,
      plan_text: planText.value,
      task_category: task.value?.task_type || task.value?.problem_type || '',
      target_column: task.value?.target_column || '',
      metric: task.value?.metric || '',
    })
    message.value = '执行方案已提交审核，管理员通过后会出现在社区广场。'
  } catch (err) {
    error.value = err.message
  }
}

async function openPlanEditor() {
  error.value = ''
  try {
    if (!planText.value.trim()) await refreshPlanText({ sync: true })
    if (!planText.value.trim()) throw new Error(`当前任务还没有加载到 ${modelDisplayName.value} 执行方案。`)
    planEditorOpen.value = true
  } catch (err) {
    error.value = err.message
  }
}

function confirmPlanEditor() {
  planEditorOpen.value = false
  message.value = '执行方案已确认，可发布到方案广场'
}

async function pauseRunningTask() {
  if (!pausable.value) return
  if (!window.confirm('暂停当前运行任务？Codex 会中断当前轮次，之后可以继续同一个任务工作区。')) return
  try {
    const data = await pauseTask(props.taskId)
    task.value = { ...(task.value || {}), ...(data || {}), status: data.status || 'paused_for_review' }
    message.value = '任务已暂停'
    closeStream()
    await load()
  } catch (err) {
    error.value = err.message
  }
}

async function continueRun() {
  if (!props.taskId || loading.value || !canContinueRun.value) return
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const data = await rerunTask(props.taskId, {}, continueRunOptions(task.value, taskRun.value, { planText: planText.value }))
    task.value = { ...(task.value || {}), ...(data || {}) }
    message.value = '任务已继续运行'
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function removeTask() {
  if (!window.confirm('删除任务历史和本地产物？')) return
  try {
    await deleteTask(props.taskId)
    await router.push('/tasks')
  } catch (err) {
    error.value = err.message
  }
}

function mergeSnapshot(data) {
  task.value = {
    ...task.value,
    status: data.status,
    error: data.error,
    updated_at: data.updated_at,
    display_name: data.display_name || task.value?.display_name,
    llm_usage: data.llm_usage || task.value?.llm_usage,
  }
  steps.value = data.steps || steps.value
}

function connectStream() {
  codexStream.connect()
}

function closeStream() {
  codexStream.close()
}

function scheduleSnapshotRefresh() {
  if (!isLiveCodexRun.value) return
  if (snapshotRefreshTimer) window.clearTimeout(snapshotRefreshTimer)
  snapshotRefreshTimer = window.setTimeout(() => {
    refreshRuntimeSnapshot().catch(() => {})
  }, 1800)
}

async function openHitlApproval(step = null) {
  if (!canHandleHitl.value) return
  if (step && !isHumanWaitingStatus(step.status)) return
  error.value = ''
  hitl.value = null
  hitlLoadError.value = ''
  hitlLoading.value = true
  hitlModalOpen.value = true
  try {
    hitl.value = await getHitl(props.taskId)
  } catch (err) {
    hitlLoadError.value = err.message
  } finally {
    hitlLoading.value = false
  }
}

async function handleHitlSubmitted(data) {
  hitlModalOpen.value = false
  hitl.value = null
  message.value = data?.message || '人工确认已提交'
  if (data?.status && task.value) {
    task.value = { ...task.value, status: data.status, error: null }
  }
  try {
    await refreshRuntimeSnapshot()
  } catch (err) {
    error.value = err.message
  }
}

onMounted(load)
onUnmounted(() => {
  closeStream()
  if (snapshotRefreshTimer) window.clearTimeout(snapshotRefreshTimer)
})
</script>

<template>
  <PageHeader :title="displayTaskTitle(task, '任务详情')" :description="taskId">
    <template #actions>
      <button class="secondary-action refresh-action" type="button" :disabled="loading" @click="load">
        <RefreshCw :class="{ spinning: loading }" :size="18" />刷新
      </button>
      <button class="primary-action" type="button" @click="router.push('/tasks')">返回</button>
      <button v-if="canContinueRun" class="secondary-action" type="button" :disabled="loading" @click="continueRun">
        <Play :size="18" />{{ runActionLabel }}
      </button>
      <button v-if="canHandleHitl" class="primary-action" type="button" :disabled="loading" @click="openHitlApproval(waitingStep)">
        <CheckCircle2 :size="18" />处理人工确认
      </button>
      <button v-if="pausable" class="secondary-action" type="button" @click="pauseRunningTask">暂停运行</button>
      <button class="danger-action" type="button" @click="removeTask"><Trash2 :size="18" />删除</button>
    </template>
  </PageHeader>

  <TaskFlowSteps :current-step="taskFlowStep" />

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="message" class="form-success">{{ message }}</p>
  <p v-if="readOnlyMode" class="form-warning">
    当前有任务 {{ activeTaskId }} 正在进行；此任务以只读方式打开，不会触发执行动作，历史运行记录仍可查看。
  </p>

  <LoadingBlock v-if="loading" />

  <template v-else>
  <div v-if="canHandleHitl" class="form-warning progress-alert">
    <span>当前任务正在等待人工确认。</span>
    <button class="primary-action compact-action" type="button" @click="openHitlApproval(waitingStep)">
      处理人工确认
    </button>
  </div>

  <section class="detail-top">
    <MetricCard label="状态" :value="taskStatusLabel(task?.status)" />
    <MetricCard label="任务类型" :value="taskTypeLabel(task?.task_type)" />
    <MetricCard label="大模型用量" :value="llmUsageText" />
    <StatusBadge v-if="task?.status" :status="task.status" />
  </section>

  <div class="detail-section-selector">
    <p>详情视图</p>
    <select :value="activeTab" @change="setActiveTab($event.target.value)">
      <option v-for="section in detailSections" :key="section.value" :value="section.value">
        {{ section.label }}
      </option>
    </select>
  </div>

  <LoadingBlock v-if="sectionLoading" />

  <TaskOverviewPanel
    v-else-if="activeTab === 'overview'"
    :overview-conclusion="overviewConclusion"
    :primary-metric="primaryMetric"
    :overview-check-items="overviewCheckItems"
    :overview-badges="overviewBadges"
    :target-summaries="targetSummaries"
    :overview-factor-description="overviewFactorDescription"
    :overview-factors="overviewFactors"
    :show-realtime="showRealtime"
    :codex-realtime="codexRealtime"
    :strategy-overview="strategyOverview"
    :token-observability="tokenObservability"
  />

  <section v-else-if="activeTab === 'report'" class="panel readable">
    <div class="panel-title">
      <span>最终报告</span>
    </div>
    <article class="markdown-report" v-html="renderedReport"></article>
  </section>

  <TaskPredictionPanel
    v-else-if="activeTab === 'demo'"
    :delivery="delivery"
    :read-only-mode="readOnlyMode"
    :prediction-loading="predictionLoading"
    :prediction-error="predictionError"
    :prediction-status-text="predictionStatusText"
    :prediction-result="predictionResult"
    :prediction-result-label="predictionResultLabel"
    :prediction-result-value="predictionResultValue"
    :prediction-result-note="predictionResultNote"
    @predict="runPredict"
  />

  <section v-else-if="activeTab === 'code'" class="panel">
    <div class="panel-title">
      <span>训练源码</span>
      <button class="secondary-action" type="button" :disabled="!canEditCode" @click="validateCode"><Play :size="18" />验证</button>
      <button class="secondary-action" type="button" :disabled="!canEditCode" @click="saveCode"><Save :size="18" />保存</button>
    </div>
    <p v-if="codeLoadDetail && !codeEditable" class="muted">{{ codeLoadDetail }}</p>
    <pre v-if="codeValidation">{{ JSON.stringify(codeValidation, null, 2) }}</pre>
    <textarea v-model="code" class="code-editor" rows="24" :readonly="!canEditCode" />
  </section>

  <section v-else class="publish-stack">
    <div class="panel form-stack">
      <div class="panel-title"><span>提交提示词审核</span></div>
      <p class="muted">把当前任务的主题和描述提交给管理员审核，通过后会进入提示词广场。</p>
      <label class="field"><span>提示词名称</span><input v-model="promptName" /></label>
      <label class="field"><span>描述信息</span><textarea v-model="promptDescription" rows="7" /></label>
      <button class="primary-action" type="button" :disabled="readOnlyMode || !promptName || !promptDescription" @click="publishTaskPrompt">
        <Send :size="18" />提交审核
      </button>
    </div>
    <div class="panel form-stack">
      <div class="panel-title"><span>提交执行方案审核</span></div>
      <p class="muted">把 {{ modelDisplayName }} 已生成并确认过的规划方案提交给管理员审核，通过后会进入方案广场。</p>
      <label class="field"><span>方案名称</span><input v-model="planName" /></label>
      <label class="field"><span>适用说明</span><textarea v-model="planDescription" rows="3" /></label>
      <div class="field">
        <span>{{ modelDisplayName }} 执行方案</span>
        <div class="plan-review-card">
          <div>
            <strong>{{ planText.trim() ? '已生成执行方案' : '未加载执行方案' }}</strong>
            <p>{{ planPreview }}</p>
          </div>
          <button class="secondary-action" type="button" @click="openPlanEditor">
            查看/编辑方案
          </button>
        </div>
      </div>
      <button class="primary-action" type="button" :disabled="readOnlyMode || !planName" @click="publishTaskPlan">
        <Send :size="18" />提交审核
      </button>
    </div>
  </section>
  </template>

  <HitlApprovalModal
    :open="hitlModalOpen"
    :task-id="taskId"
    :hitl="hitl"
    :loading="hitlLoading"
    :load-error="hitlLoadError"
    @close="hitlModalOpen = false"
    @submitted="handleHitlSubmitted"
  />

  <div v-if="planEditorOpen" class="modal-backdrop" @click.self="planEditorOpen = false">
    <section class="modal-panel plan-editor-modal" role="dialog" aria-modal="true" aria-label="确认执行方案">
      <div class="modal-head">
        <div>
          <span class="panel-eyebrow">{{ modelDisplayName }} PLAN</span>
          <h2>确认执行方案</h2>
          <p>这里展示的是当前任务已生成的 {{ modelDisplayName }} plan，可在发布前直接修改。</p>
        </div>
        <button class="icon-button modal-close" type="button" @click="planEditorOpen = false">
          <X :size="18" />
        </button>
      </div>
      <div class="form-stack plan-editor-body">
        <label class="field">
          <span>方案内容</span>
          <textarea v-model="planText" class="plan-editor-textarea" rows="18" />
        </label>
        <div class="form-actions end">
          <button class="secondary-action" type="button" @click="planEditorOpen = false">取消</button>
          <button class="primary-action" type="button" :disabled="!planText.trim()" @click="confirmPlanEditor">
            确认方案
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
