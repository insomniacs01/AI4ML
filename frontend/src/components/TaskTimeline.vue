<script setup>
import { CheckCircle2, Circle, LoaderCircle, XCircle } from 'lucide-vue-next'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  interactiveHitl: { type: Boolean, default: true },
  compact: { type: Boolean, default: false },
})
const emit = defineEmits(['hitl-request'])

function stepIcon(status) {
  if (status === 'completed') return CheckCircle2
  if (status === 'failed') return XCircle
  if (status === 'cancelled') return XCircle
  if (status === 'running') return LoaderCircle
  return Circle
}

function statusLabel(status) {
  return {
    completed: '完成',
    failed: '失败',
    cancelled: '已取消',
    running: '运行中',
    waiting_human: '待人工确认',
    pending: '等待',
  }[status] || status || '等待'
}

function stepTitle(step) {
  return step?.title || step?.name || step?.node || step?.agent_role || '运行步骤'
}

function stepDescription(step) {
  if (step?.message || step?.summary) return step.message || step.summary
  return {
    completed: '该阶段已完成，相关状态已写入运行记录。',
    failed: '该阶段执行失败，请查看运行记录或任务详情。',
    cancelled: '该阶段已取消，后续执行已停止。',
    running: '正在执行该阶段，等待产物和状态写入。',
    waiting_human: '需要处理人工确认后才能继续执行。',
    pending: '等待前置阶段完成。',
  }[step?.status] || '等待前置阶段完成。'
}

function shortUrl(url) {
  const text = String(url || '')
  return text.length > 42 ? `${text.slice(0, 39)}...` : text
}

function isHitlStep(step) {
  return props.interactiveHitl && step?.status === 'waiting_human'
}

function handleStepClick(step) {
  if (isHitlStep(step)) emit('hitl-request', step)
}

function activityKey(item, index) {
  return `${item.kind || 'activity'}-${item.label || ''}-${item.value || ''}-${index}`
}
</script>

<template>
  <div class="agent-workbench" :class="{ compact: compact }">
    <div class="agent-board">
      <div
        v-for="(step, index) in steps"
        :key="step.id || `${step.name || step.node || 'step'}-${index}`"
        class="agent-card"
        :class="[step.status, step.name, { actionable: isHitlStep(step) }]"
        :role="isHitlStep(step) ? 'button' : undefined"
        :tabindex="isHitlStep(step) ? 0 : undefined"
        @click="handleStepClick(step)"
        @keydown.enter="handleStepClick(step)"
        @keydown.space.prevent="handleStepClick(step)"
      >
        <div class="agent-status">
          <component :is="stepIcon(step.status)" :size="18" />
        </div>
        <div class="agent-body">
          <div class="agent-head">
            <div class="agent-title-block">
              <strong>{{ stepTitle(step) }}</strong>
              <small v-if="step.agent_role">{{ step.agent_role }}</small>
            </div>
            <span>{{ statusLabel(step.status) }}</span>
          </div>
          <p>{{ stepDescription(step) }}</p>
          <div v-if="!compact && step.activity_items?.length" class="agent-activity-grid">
            <div
              v-for="(item, activityIndex) in step.activity_items.slice(0, 6)"
              :key="activityKey(item, activityIndex)"
              class="agent-activity-card"
              :class="[item.kind, item.status]"
            >
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
              <small v-if="item.detail">{{ item.detail }}</small>
            </div>
          </div>
          <div v-if="!compact && (step.decision || step.duration_s || step.artifacts?.length)" class="agent-meta">
            <span v-if="step.decision">决策：{{ step.decision }}</span>
            <span v-if="step.decision_reason">依据：{{ step.decision_reason }}</span>
            <span v-if="step.duration_s">耗时：{{ Number(step.duration_s).toFixed(1) }}s</span>
            <span v-if="step.artifacts?.length">产物：{{ step.artifacts.length }}</span>
          </div>
          <div v-if="!compact && step.tool_calls?.length" class="agent-tool-strip">
            <span v-for="tool in step.tool_calls.slice(0, 4)" :key="tool.name || tool.query">
              {{ tool.name || '工具' }} · {{ tool.status || '完成' }}
            </span>
          </div>
          <div v-if="!compact && step.search_findings?.length" class="search-finding-list">
            <a
              v-for="item in step.search_findings.slice(0, 3)"
              :key="`${item.source}-${item.title}`"
              :href="item.url || '#'"
              target="_blank"
              rel="noreferrer"
            >
              <strong>{{ item.source }}：{{ item.title }}</strong>
              <span>{{ item.adaptation_suggestion || item.summary || shortUrl(item.url) }}</span>
            </a>
          </div>
          <div v-if="!compact && step.warnings?.length" class="agent-warnings">
            <span v-for="item in step.warnings.slice(0, 3)" :key="item">{{ item }}</span>
          </div>
          <button
            v-if="isHitlStep(step)"
            class="primary-action compact-action hitl-card-action"
            type="button"
            @click.stop="emit('hitl-request', step)"
          >
            <CheckCircle2 :size="17" />处理人工确认
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
