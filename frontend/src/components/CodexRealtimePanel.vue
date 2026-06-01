<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import {
  Brain,
  CheckCircle2,
  Circle,
  FileText,
  LoaderCircle,
  MessageSquare,
  Play,
  Settings2,
  XCircle,
} from 'lucide-vue-next'
import { modelDisplayName } from '@/utils/modelProfile'

const props = defineProps({
  events: {
    type: Array,
    default: () => [],
  },
  status: {
    type: String,
    default: 'idle',
  },
  activity: {
    type: Object,
    default: null,
  },
})

const frameRef = ref(null)

const visibleEvents = computed(() => props.events)
const isBusy = computed(() => props.status === 'running' || (props.status !== 'snapshot' && props.activity?.status === 'busy'))
const statusText = computed(() => {
  if (isBusy.value) return '运行中'
  if (props.status === 'connected') return '已连接'
  if (props.status === 'replaying') return '同步历史'
  if (props.status === 'snapshot') return '历史进度'
  if (props.status === 'idle') return '待连接'
  if (props.status === 'closed') return '连接已断开'
  if (props.status === 'error') return '连接异常'
  return props.status || '未知'
})
const statusClass = computed(() => {
  if (isBusy.value) return 'busy'
  if (props.status === 'connected') return 'good'
  if (props.status === 'snapshot') return 'good'
  if (props.status === 'idle') return 'muted'
  if (props.status === 'closed') return 'muted'
  if (props.status === 'error') return 'bad'
  return ''
})
const activityText = computed(() => {
  if (props.status === 'snapshot') return `状态 · ${statusText.value}`
  return props.activity?.message || `状态 · ${statusText.value}`
})

const promptEvent = computed(() =>
  [...visibleEvents.value].reverse().find((event) => event.kind === 'prompt' || event.kind === 'input'),
)
const promptText = computed(() => formatPrompt(promptEvent.value))
const assistantMessages = computed(() =>
  visibleEvents.value.filter((event) => event.kind === 'assistant' && event.text),
)
const usageEvent = computed(() => [...visibleEvents.value].reverse().find((event) => event.kind === 'usage') || null)
const workingMessages = computed(() =>
  visibleEvents.value.filter((event) => event.kind === 'working' && event.text),
)
const latestWorking = computed(() => workingMessages.value.at(-1) || null)
const toolEvents = computed(() =>
  visibleEvents.value.filter((event) => event.kind === 'tool' || event.kind === 'error'),
)
const milestoneEvents = computed(() =>
  visibleEvents.value.filter((event) => ['session', 'workspace', 'requirements', 'plan', 'approval', 'modeling', 'report'].includes(event.kind)),
)
const latestTurn = computed(() => [...visibleEvents.value].reverse().find((event) => event.kind === 'turn') || null)
const turnCompleted = computed(() =>
  latestTurn.value?.raw?.type === 'turn_completed'
  || latestTurn.value?.title === `${modelDisplayName.value} 回合完成`
  || latestTurn.value?.title === 'Codex 回合完成',
)
const hasWorkingContent = computed(() => Boolean(latestWorking.value || toolEvents.value.length))
const hasAnyContent = computed(() =>
  Boolean(promptText.value || assistantMessages.value.length || hasWorkingContent.value || usageEvent.value),
)
const workingTitle = computed(() => {
  if (isBusy.value) return 'Working'
  if (latestTurn.value?.raw?.durationMs) return `Worked for ${formatDuration(latestTurn.value.raw.durationMs)}`
  return 'Working'
})

watch(
  () => props.events.length,
  async () => {
    await nextTick()
    if (frameRef.value && isBusy.value) frameRef.value.scrollTop = frameRef.value.scrollHeight
  },
)

function formatPrompt(event) {
  if (!event) return ''
  const lines = []
  if (event.raw?.dataPath) lines.push(`数据路径：${event.raw.dataPath}`)
  if (event.raw?.dataPathType) lines.push(`数据类型：${event.raw.dataPathType}`)
  if (event.raw?.description) lines.push(`任务描述：${event.raw.description}`)
  if (lines.length) return lines.join('\n')
  return event.text || ''
}

function eventTime(event) {
  if (!event?.updatedAt) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(event.updatedAt))
}

function formatDuration(ms) {
  if (!ms || ms < 0) return ''
  const totalSeconds = Math.max(1, Math.round(ms / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (!minutes) return `${seconds}s`
  return `${minutes}m ${seconds}s`
}

function toolIcon(event) {
  if (event.kind === 'error') return XCircle
  if (event.tool === 'file_change' || /file|changed/i.test(event.title || '')) return FileText
  return Play
}

function toolTitle(event) {
  if (event.kind === 'error' && event.title === '命令输出') return '执行异常'
  if (event.title === '命令输出') return 'Ran command'
  return event.title || '工具事件'
}

function toolMeta(event) {
  const parts = []
  if (event.status) parts.push(event.status)
  else if (event.done) parts.push('completed')
  if (Number.isFinite(event.exitCode)) parts.push(`exit ${event.exitCode}`)
  if (event.durationMs) parts.push(formatDuration(event.durationMs))
  return parts.join(' · ')
}
</script>

<template>
  <section id="codex-realtime" class="panel codex-realtime-panel">
    <header class="codex-chat-head">
      <div>
        <span class="eyebrow">{{ modelDisplayName }} LIVE</span>
        <h2><Play :size="22" /> {{ modelDisplayName }} 实时运行</h2>
        <p>{{ activityText }}</p>
      </div>
      <span class="codex-stream-status" :class="statusClass">{{ statusText }}</span>
    </header>

    <div ref="frameRef" class="codex-chat-frame">
      <article v-if="promptText" class="codex-message-row user">
        <div class="codex-user-bubble">
          <p>{{ promptText }}</p>
        </div>
      </article>

      <div v-if="milestoneEvents.length" class="codex-milestone-strip">
        <div v-for="event in milestoneEvents" :key="event.id" class="codex-milestone">
          <CheckCircle2 v-if="event.kind === 'report'" :size="16" />
          <Circle v-else :size="16" />
          <span>{{ event.title }}</span>
          <small>{{ eventTime(event) }}</small>
        </div>
      </div>

      <details v-if="hasWorkingContent" class="codex-working-shell" :open="isBusy">
        <summary class="codex-working-summary">
          <span>
            <LoaderCircle v-if="isBusy" :size="18" class="spin-icon" />
            <Circle v-else :size="18" />
            <strong>{{ workingTitle }}</strong>
          </span>
          <small>{{ toolEvents.length }} 个工具事件</small>
        </summary>

        <div class="codex-working-body">
          <p v-if="latestWorking?.text" class="codex-working-text">{{ latestWorking.text }}</p>

          <div v-if="toolEvents.length" class="codex-tool-list">
            <details v-for="event in toolEvents" :key="event.id" class="codex-tool-row" :class="{ error: event.kind === 'error' }">
              <summary>
                <component :is="toolIcon(event)" :size="16" />
                <strong>{{ toolTitle(event) }}</strong>
                <span>{{ toolMeta(event) || eventTime(event) }}</span>
              </summary>
              <div class="codex-tool-detail">
                <p v-if="event.cwd" class="codex-tool-path">{{ event.cwd }}</p>
                <pre v-if="event.command" class="codex-command">{{ event.command }}</pre>
                <pre v-if="event.stdout" class="codex-output">{{ event.stdout }}</pre>
                <pre v-if="event.stderr" class="codex-output stderr">{{ event.stderr }}</pre>
              </div>
            </details>
          </div>
        </div>
      </details>

      <article v-for="message in assistantMessages" :key="message.id" class="codex-message-row assistant">
        <div class="codex-assistant-icon"><Brain :size="18" /></div>
        <div class="codex-assistant-message">
          <div class="codex-message-meta">
            <strong>{{ modelDisplayName }}</strong>
            <span>{{ eventTime(message) }}</span>
          </div>
          <p>{{ message.text }}</p>
        </div>
      </article>

      <div v-if="!hasAnyContent" class="codex-chat-empty">
        <MessageSquare :size="24" />
        <strong>等待 {{ modelDisplayName }} 输出</strong>
        <span>任务开始后，这里会显示提示词、Working 状态和 {{ modelDisplayName }} 回复。</span>
      </div>

      <div v-if="!assistantMessages.length && hasAnyContent" class="codex-chat-note">
        <Settings2 :size="16" />
        <span>{{ modelDisplayName }} 正在执行，回复内容会在生成后出现在这里。</span>
      </div>

      <div v-if="usageEvent" class="codex-chat-note done">
        <CheckCircle2 :size="16" />
        <span>{{ usageEvent.text || usageEvent.title }}</span>
      </div>

      <div v-if="turnCompleted" class="codex-chat-note done">
        <CheckCircle2 :size="16" />
        <span>{{ modelDisplayName }} 回合完成</span>
      </div>
    </div>
  </section>
</template>
