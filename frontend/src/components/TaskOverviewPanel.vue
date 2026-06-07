<script setup>
import { computed } from 'vue'
import { CheckCircle2, FileText } from 'lucide-vue-next'
import CodexRealtimePanel from '@/components/CodexRealtimePanel.vue'

const props = defineProps({
  overviewConclusion: { type: String, required: true },
  primaryMetric: { type: Object, default: null },
  overviewCheckItems: { type: Array, default: () => [] },
  overviewBadges: { type: Array, default: () => [] },
  targetSummaries: { type: Array, default: () => [] },
  overviewFactorDescription: { type: String, required: true },
  overviewFactors: { type: Array, default: () => [] },
  showRealtime: { type: Boolean, default: false },
  codexRealtime: { type: Object, default: () => ({ events: [], status: 'idle', activity: '' }) },
  strategyOverview: { type: Object, default: null },
  tokenObservability: { type: Object, default: null },
})

function isLongText(value, limit = 72) {
  return String(value || '').length > limit
}

const tokenChart = computed(() => {
  const usage = props.tokenObservability || {}
  const inputTokens = Number(usage.inputTokens || 0)
  const outputTokens = Number(usage.outputTokens || 0)
  const cachedInputTokens = Math.min(inputTokens, Number(usage.cachedInputTokens || 0))
  const uncachedInputTokens = Number.isFinite(Number(usage.uncachedInputTokens))
    ? Number(usage.uncachedInputTokens)
    : Math.max(0, inputTokens - cachedInputTokens)
  const measuredTotal = uncachedInputTokens + cachedInputTokens + outputTokens
  if (!measuredTotal) {
    return {
      available: false,
      uncachedInputPercent: 0,
      cachedInputPercent: 0,
      outputPercent: 0,
      style: {
        '--token-uncached-angle': '0deg',
        '--token-cached-angle': '0deg',
      },
      segments: [],
    }
  }
  const uncachedInputPercent = Math.round((uncachedInputTokens / measuredTotal) * 100)
  const cachedInputPercent = Math.round((cachedInputTokens / measuredTotal) * 100)
  const outputPercent = Math.max(0, 100 - uncachedInputPercent - cachedInputPercent)
  const cachedAngle = (uncachedInputPercent + cachedInputPercent) * 3.6
  return {
    available: true,
    uncachedInputPercent,
    cachedInputPercent,
    outputPercent,
    style: {
      '--token-uncached-angle': `${uncachedInputPercent * 3.6}deg`,
      '--token-cached-angle': `${cachedAngle}deg`,
    },
    segments: [
      { key: 'uncached', label: '非缓存输入', value: usage.uncachedInputText, percent: uncachedInputPercent },
      { key: 'cached', label: '缓存输入', value: usage.cachedInputText, percent: cachedInputPercent },
      { key: 'output', label: '输出', value: usage.outputText, percent: outputPercent },
    ],
  }
})

const tokenDetailItems = computed(() => {
  const usage = props.tokenObservability || {}
  return [
    { key: 'input', label: '输入总量', value: usage.inputText },
    { key: 'uncached', label: '非缓存输入', value: usage.uncachedInputText },
    { key: 'cached', label: '缓存输入', value: usage.cachedInputText },
    { key: 'output', label: '输出', value: usage.outputText },
    { key: 'reasoning', label: '推理输出', value: usage.reasoningOutputText || '-', note: '包含在输出中' },
    { key: 'cache_write', label: '缓存写入', value: '未记录' },
  ]
})

const checkPreviewItems = computed(() => props.overviewCheckItems.slice(0, 3))
const remainingCheckItems = computed(() => props.overviewCheckItems.slice(3))
</script>

<template>
  <section class="overview-board">
    <article class="panel overview-summary-strip">
      <div class="overview-summary-main">
        <div class="overview-card-head">
          <span class="overview-card-icon"><FileText :size="18" /></span>
          <span>结果概览</span>
        </div>
        <strong class="overview-core-title" :title="overviewConclusion">{{ overviewConclusion }}</strong>
        <details v-if="isLongText(overviewConclusion, 72)" class="overview-expand">
          <summary>展开完整结论</summary>
          <p>{{ overviewConclusion }}</p>
        </details>
      </div>

      <div v-if="primaryMetric || targetSummaries.length" class="overview-summary-metrics">
        <div v-if="primaryMetric" class="overview-primary-metric">
          <span>主指标</span>
          <strong :title="primaryMetric.label">{{ primaryMetric.label }}</strong>
          <p :title="primaryMetric.value">{{ primaryMetric.value }}</p>
        </div>
        <div v-if="targetSummaries.length" class="overview-target-strip">
          <span
            v-for="item in targetSummaries"
            :key="item.name"
            :title="item.metric ? `${item.name} · ${item.metric} ${item.value}` : item.name"
          >
            {{ item.name }}{{ item.metric ? ` · ${item.metric} ${item.value}` : '' }}
          </span>
        </div>
      </div>
      <p v-if="!primaryMetric && !targetSummaries.length" class="muted">当前任务没有返回结构化主指标。</p>
    </article>

    <div class="overview-analysis-grid">
      <article v-if="tokenObservability" class="panel overview-token-panel">
        <div class="overview-panel-head stacked">
          <h3>Token 观察</h3>
          <p>{{ tokenObservability.comparison?.text || '暂无历史对比。' }}</p>
        </div>

        <div v-if="tokenChart.available" class="token-chart-layout">
          <div
            class="token-donut"
            :style="tokenChart.style"
            role="img"
            :aria-label="`Token 非缓存输入占比 ${tokenChart.uncachedInputPercent}%，缓存输入占比 ${tokenChart.cachedInputPercent}%，输出占比 ${tokenChart.outputPercent}%`"
          >
            <div>
              <span>总量</span>
              <strong>{{ tokenObservability.totalText }}</strong>
            </div>
          </div>
          <div class="token-legend-list">
            <div v-for="segment in tokenChart.segments" :key="segment.key" class="token-legend-item" :class="segment.key">
              <span><i></i>{{ segment.label }}</span>
              <strong>{{ segment.value }}</strong>
              <small>{{ segment.percent }}%</small>
            </div>
          </div>
        </div>
        <div v-else class="token-empty-state">
          <span>暂无真实 Token 用量</span>
          <strong>{{ tokenObservability.totalText }}</strong>
        </div>

        <div class="token-detail-grid">
          <div v-for="item in tokenDetailItems" :key="item.key">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
            <small v-if="item.note">{{ item.note }}</small>
          </div>
        </div>

        <ul class="token-reason-list">
          <li v-for="item in tokenObservability.reasons" :key="item">{{ item }}</li>
        </ul>
      </article>

      <section class="panel overview-factor-panel">
        <div class="overview-panel-head stacked">
          <h3>特征影响排序</h3>
          <p>{{ overviewFactorDescription }}</p>
          <small class="overview-factor-note">相对重要性，以最高特征为 100%。</small>
        </div>
        <div class="overview-factor-chart">
          <div v-for="(item, index) in overviewFactors" :key="item.label" class="overview-factor-row">
            <div class="overview-factor-meta">
              <span>{{ index + 1 }}</span>
              <strong :title="item.label">{{ item.label }}</strong>
              <small>{{ item.percent }}%</small>
            </div>
            <div class="overview-factor-track" :aria-label="`${item.label} ${item.percent}%`">
              <span :style="{ width: `${item.percent}%` }"></span>
            </div>
          </div>
          <p v-if="!overviewFactors.length" class="muted">当前任务没有返回真实特征重要性或诊断因素。</p>
        </div>
      </section>
    </div>

    <article v-if="strategyOverview" class="panel overview-strategy-strip">
      <div class="overview-strip-head">
        <div>
          <h3>执行配置</h3>
          <p>{{ strategyOverview.reason }}</p>
        </div>
        <span>{{ strategyOverview.label }}</span>
      </div>
      <div class="strategy-strip-grid">
        <div v-for="item in strategyOverview.items" :key="item.label">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
    </article>

    <section class="panel overview-check-panel overview-check-compact">
      <div class="overview-panel-head">
        <div>
          <h3>系统检查</h3>
          <p>默认展示关键检查，完整记录可展开查看。</p>
        </div>
        <span>{{ overviewCheckItems.length }} 项</span>
      </div>
      <ul class="overview-check-list preview">
        <li v-for="item in checkPreviewItems" :key="item.label">
          <CheckCircle2 :size="16" />
          <span>{{ item.label }}</span>
          <strong :title="item.value">{{ item.value }}</strong>
        </li>
      </ul>
      <details v-if="remainingCheckItems.length" class="overview-check-details">
        <summary>查看剩余 {{ remainingCheckItems.length }} 项检查</summary>
        <ul class="overview-check-list">
          <li v-for="item in remainingCheckItems" :key="item.label">
            <CheckCircle2 :size="16" />
            <span>{{ item.label }}</span>
            <strong :title="item.value">{{ item.value }}</strong>
          </li>
        </ul>
      </details>
      <div class="overview-badge-row">
        <span v-for="badge in overviewBadges" :key="badge">{{ badge }}</span>
      </div>
    </section>

    <CodexRealtimePanel
      v-if="showRealtime"
      :events="codexRealtime.events"
      :status="codexRealtime.status"
      :activity="codexRealtime.activity"
    />
  </section>
</template>
