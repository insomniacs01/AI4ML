<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { PlusCircle, RefreshCw, Search, Trash2, XCircle } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import { deleteTask, getTasks, pauseTask } from '@/api/client'
import { formatDateTime } from '@/utils/formatters'
import { displayTaskTitle, taskTypeLabel } from '@/utils/labels'

const tasks = ref([])
const loading = ref(false)
const error = ref('')
const busyTaskIds = ref(new Set())
const activeFilter = ref('all')
const searchTerm = ref('')
const router = useRouter()

const statusFilters = computed(() => [
  { key: 'all', label: '全部', count: tasks.value.length },
  { key: 'needs_action', label: '需要我处理', count: tasks.value.filter((task) => ['uploaded', 'planning', 'waiting_human', 'paused_for_review'].includes(task.status)).length },
  { key: 'running', label: '运行中', count: tasks.value.filter((task) => task.status === 'running').length },
  { key: 'completed', label: '已完成', count: tasks.value.filter((task) => task.status === 'completed').length },
  { key: 'problem', label: '遇到问题', count: tasks.value.filter((task) => ['failed', 'cancelled'].includes(task.status)).length },
])

const filteredTasks = computed(() => {
  const keyword = searchTerm.value.trim().toLowerCase()
  return tasks.value.filter((task) => {
    const statusMatched = activeFilter.value === 'all'
      || (activeFilter.value === 'needs_action' && ['uploaded', 'planning', 'waiting_human', 'paused_for_review'].includes(task.status))
      || (activeFilter.value === 'running' && task.status === 'running')
      || (activeFilter.value === 'completed' && task.status === 'completed')
      || (activeFilter.value === 'problem' && ['failed', 'cancelled'].includes(task.status))
    if (!statusMatched) return false
    if (!keyword) return true
    const haystack = [
      displayTaskTitle(task),
      task.task_id,
      datasetName(task),
      task.target_column,
      taskTypeLabel(task.task_type),
      task.status,
    ].filter(Boolean).join(' ').toLowerCase()
    return haystack.includes(keyword)
  })
})

function canPause(task) {
  return task.status === 'running'
}

function isBusy(task) {
  return busyTaskIds.value.has(task.task_id)
}

function setTaskBusy(taskId, busy) {
  const next = new Set(busyTaskIds.value)
  if (busy) next.add(taskId)
  else next.delete(taskId)
  busyTaskIds.value = next
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await getTasks()
    tasks.value = data.items || []
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function pauseItem(task) {
  if (!window.confirm('暂停这个任务？之后可以从当前工作区继续运行。')) return
  const taskId = task.task_id
  setTaskBusy(taskId, true)
  tasks.value = tasks.value.map((item) => (
    item.task_id === taskId ? { ...item, status: 'paused_for_review' } : item
  ))
  try {
    const data = await pauseTask(taskId)
    tasks.value = tasks.value.map((item) => (
      item.task_id === taskId ? { ...item, ...data, status: data.status || 'paused_for_review' } : item
    ))
    await load()
  } catch (err) {
    error.value = err.message
    await load()
  } finally {
    setTaskBusy(taskId, false)
  }
}

async function deleteItem(task) {
  if (!window.confirm('删除这个任务历史？')) return
  const taskId = task.task_id
  setTaskBusy(taskId, true)
  try {
    await deleteTask(taskId)
    tasks.value = tasks.value.filter((item) => item.task_id !== taskId)
    await load()
  } catch (err) {
    error.value = err.message
  } finally {
    setTaskBusy(taskId, false)
  }
}

async function goCreate() {
  try {
    await router.push('/create')
  } catch {
    window.location.assign('/create')
  }
}

function datasetName(task) {
  return task.dataset_name || task.dataset_filename || task.dataset_path?.split(/[\\/]/).pop() || '未上传'
}

function statusMeta(task) {
  const map = {
    waiting_human: { label: '需要我处理', next: '下一步：确认方案并继续执行', tone: 'warning', mark: '!' },
    running: { label: '运行中', next: '下一步：查看实时状态', tone: 'running', mark: '•' },
    paused_for_review: { label: '已暂停', next: '下一步：进入详情继续运行', tone: 'warning', mark: 'Ⅱ' },
    uploaded: { label: '待启动', next: '下一步：进入详情启动运行', tone: 'warning', mark: '▷' },
    planning: { label: '待启动', next: '下一步：进入详情启动运行', tone: 'warning', mark: '▷' },
    completed: { label: '已完成', next: '下一步：查看结果报告', tone: 'success', mark: '✓' },
    failed: { label: '遇到问题', next: '下一步：查看错误诊断', tone: 'danger', mark: '!' },
    cancelled: { label: '已取消', next: '下一步：查看任务详情', tone: 'muted', mark: '×' },
  }
  return map[task.status] || { label: task.status || '未同步', next: '下一步：查看任务详情', tone: 'muted', mark: '•' }
}

function taskProgress(task) {
  if (task.status === 'completed') return 100
  if (['failed', 'cancelled'].includes(task.status)) return 0
  if (['waiting_human', 'paused_for_review'].includes(task.status)) return 25
  if (task.status === 'running') return 30
  return 0
}

function ringStyle(task) {
  const percent = taskProgress(task)
  return { background: `conic-gradient(var(--accent) ${percent * 3.6}deg, var(--surface-soft) 0deg)` }
}

onMounted(load)
</script>

<template>
  <PageHeader title="我的任务" description="按状态查看每个建模任务，先看结论，再进入细节。">
    <template #actions>
      <button class="secondary-action refresh-action" type="button" :disabled="loading" @click="load">
        <RefreshCw :class="{ spinning: loading }" :size="18" />刷新
      </button>
      <button class="primary-action" type="button" @click="goCreate"><PlusCircle :size="18" />开始任务</button>
    </template>
  </PageHeader>

  <p v-if="error" class="form-error">{{ error }}</p>
  <LoadingBlock v-if="loading" />
  <EmptyState v-else-if="tasks.length === 0" title="暂无任务" description="开始任务后会在这里显示运行记录。" />
  <section v-else class="tasks-board">
    <div class="task-filter-bar">
      <div class="task-filter-tabs">
        <button
          v-for="item in statusFilters"
          :key="item.key"
          type="button"
          class="task-filter-chip"
          :class="{ active: activeFilter === item.key }"
          @click="activeFilter = item.key"
        >
          {{ item.label }}
          <strong v-if="item.key !== 'all'">{{ item.count }}</strong>
        </button>
      </div>
      <label class="task-search">
        <Search :size="17" />
        <input v-model="searchTerm" placeholder="搜索任务、数据集或目标" />
      </label>
    </div>

    <EmptyState v-if="filteredTasks.length === 0" title="没有匹配的任务" description="换一个状态或关键词再试。" />
    <div v-else class="task-record-list">
      <article v-for="task in filteredTasks" :key="task.task_id" class="task-record-row" :class="statusMeta(task).tone">
        <div class="task-record-status">
          <span>{{ statusMeta(task).mark }}</span>
        </div>

        <RouterLink class="task-record-main" :to="`/tasks/${task.task_id}`">
          <strong>{{ displayTaskTitle(task) }}</strong>
          <span>创建于 {{ formatDateTime(task.created_at) }} · 数据：</span>
          <small>{{ datasetName(task) }}</small>
        </RouterLink>

        <RouterLink class="task-record-next" :to="`/tasks/${task.task_id}`">
          <strong><i></i>{{ statusMeta(task).label }}</strong>
          <span>{{ statusMeta(task).next }}</span>
        </RouterLink>

        <div class="task-record-progress" :style="ringStyle(task)">
          <strong>{{ taskProgress(task) }}%</strong>
        </div>

        <div class="task-record-actions">
          <button
            v-if="canPause(task)"
            class="secondary-action compact-action"
            type="button"
            :disabled="isBusy(task)"
            @click="pauseItem(task)"
          >
            <XCircle :size="15" />{{ isBusy(task) ? '处理中' : '暂停' }}
          </button>
          <button class="danger-action compact-action" type="button" :disabled="isBusy(task)" @click="deleteItem(task)">
            <Trash2 :size="15" />{{ isBusy(task) ? '处理中' : '删除' }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>
