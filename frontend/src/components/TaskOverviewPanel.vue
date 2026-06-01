<script setup>
import { CheckCircle2, ClipboardList, FileText, Shield } from 'lucide-vue-next'
import CodexRealtimePanel from '@/components/CodexRealtimePanel.vue'

defineProps({
  task: { type: Object, default: null },
  overviewConclusion: { type: String, required: true },
  predictionErrorText: { type: String, required: true },
  predictionErrorDescription: { type: String, required: true },
  overviewConfidence: { type: String, required: true },
  confidenceDescription: { type: String, required: true },
  overviewRecommendation: { type: String, required: true },
  overviewCheckItems: { type: Array, default: () => [] },
  overviewBadges: { type: Array, default: () => [] },
  targetSummaries: { type: Array, default: () => [] },
  overviewFactorDescription: { type: String, required: true },
  overviewFactors: { type: Array, default: () => [] },
  hasOverviewChart: { type: Boolean, default: false },
  overviewChartPoints: { type: String, default: '' },
  overviewChartPointsAlt: { type: String, default: '' },
  explanationText: { type: String, required: true },
  showRealtime: { type: Boolean, default: false },
  codexRealtime: { type: Object, default: () => ({ events: [], status: 'idle', activity: '' }) },
})

function isLongText(value, limit = 72) {
  return String(value || '').length > limit
}
</script>

<template>
  <section class="overview-board">
    <div class="overview-report-grid">
      <article class="panel overview-report-card overview-core-card">
        <div class="overview-card-head">
          <span class="overview-card-icon"><FileText :size="18" /></span>
          <span>核心结果</span>
        </div>
        <strong class="overview-core-title" :title="overviewConclusion">{{ overviewConclusion }}</strong>
        <details v-if="isLongText(overviewConclusion, 54)" class="overview-expand">
          <summary>展开完整结论</summary>
          <p>{{ overviewConclusion }}</p>
        </details>
      </article>

      <article class="panel overview-report-card overview-kpi-card">
        <div class="overview-card-head">
          <span class="overview-card-icon"><ClipboardList :size="18" /></span>
          <span>关键指标</span>
        </div>
        <div class="overview-kpi-grid">
          <div class="overview-kpi-item">
            <span>预测误差</span>
            <strong :title="predictionErrorText">{{ predictionErrorText }}</strong>
            <p :title="predictionErrorDescription">{{ predictionErrorDescription }}</p>
            <details v-if="isLongText(predictionErrorDescription, 56)" class="overview-expand">
              <summary>展开说明</summary>
              <p>{{ predictionErrorDescription }}</p>
            </details>
          </div>
          <div class="overview-kpi-item">
            <span>可信度</span>
            <strong :title="overviewConfidence">{{ overviewConfidence }}</strong>
            <p :title="confidenceDescription">{{ confidenceDescription }}</p>
            <details v-if="isLongText(confidenceDescription, 56)" class="overview-expand">
              <summary>展开说明</summary>
              <p>{{ confidenceDescription }}</p>
            </details>
          </div>
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
      </article>

      <article class="panel overview-report-card overview-advice-card">
        <div class="overview-card-head">
          <span class="overview-card-icon"><Shield :size="18" /></span>
          <span>建议</span>
        </div>
        <strong class="overview-advice-text" :title="overviewRecommendation">{{ overviewRecommendation }}</strong>
        <details v-if="isLongText(overviewRecommendation, 42)" class="overview-expand">
          <summary>展开完整建议</summary>
          <p>{{ overviewRecommendation }}</p>
        </details>
      </article>
    </div>

    <div class="overview-content-grid">
      <div class="overview-left-column">
        <section class="panel overview-check-panel">
          <div class="overview-panel-head">
            <h3>系统检查</h3>
            <span>{{ overviewCheckItems.length }} 项</span>
          </div>
          <ul class="overview-check-list">
            <li v-for="item in overviewCheckItems" :key="item.label">
              <CheckCircle2 :size="16" />
              <span>{{ item.label }}</span>
              <strong :title="item.value">{{ item.value }}</strong>
            </li>
          </ul>
          <div class="overview-badge-row">
            <span v-for="badge in overviewBadges" :key="badge">{{ badge }}</span>
          </div>
        </section>

        <section class="panel overview-factor-panel">
          <div class="overview-panel-head stacked">
            <h3>影响因素</h3>
            <p>{{ overviewFactorDescription }}</p>
          </div>
          <div class="overview-factor-list">
            <div v-for="item in overviewFactors" :key="item.label" class="overview-factor-row">
              <strong :title="item.label">{{ item.label }}</strong>
              <div><span :style="{ width: `${item.percent}%` }"></span></div>
              <small>{{ item.percent }}%</small>
            </div>
            <p v-if="!overviewFactors.length" class="muted">当前任务没有返回真实特征重要性或诊断因素。</p>
          </div>
        </section>
      </div>

      <aside class="panel overview-explain-panel">
        <div class="overview-panel-head stacked">
          <h3>结果怎么理解</h3>
          <p>辅助解释</p>
        </div>
        <div v-if="hasOverviewChart" class="overview-mini-chart">
          <svg viewBox="0 0 100 80" role="img" aria-label="结果趋势图">
            <polyline :points="overviewChartPoints" fill="none" stroke="#2563eb" stroke-width="2.2" />
            <polyline :points="overviewChartPointsAlt" fill="none" stroke="#0f8b8d" stroke-width="2.2" />
          </svg>
        </div>
        <p v-else class="muted">当前任务没有返回可绘制的真实预测对比点。</p>
        <div class="overview-insight" :title="explanationText">
          {{ explanationText }}
        </div>
        <details v-if="isLongText(explanationText, 96)" class="overview-expand">
          <summary>展开完整解释</summary>
          <p>{{ explanationText }}</p>
        </details>
      </aside>
    </div>

    <CodexRealtimePanel
      v-if="showRealtime"
      :events="codexRealtime.events"
      :status="codexRealtime.status"
      :activity="codexRealtime.activity"
    />
  </section>
</template>
