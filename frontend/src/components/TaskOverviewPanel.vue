<script setup>
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
</script>

<template>
  <section class="overview-board">
    <div class="overview-summary-grid">
      <article class="overview-summary-card conclusion">
        <span class="summary-icon">☆</span>
        <div>
          <span>结论</span>
          <strong>{{ overviewConclusion }}</strong>
          <p>{{ task?.status === 'completed' ? '完成建模后，这里会展示可读结论。' : '完成建模后，这里会展示可读结论。' }}</p>
        </div>
      </article>
      <article class="overview-summary-card">
        <span>预测误差</span>
        <strong>{{ predictionErrorText }}</strong>
        <p>{{ predictionErrorDescription }}</p>
      </article>
      <article class="overview-summary-card">
        <span>可信度</span>
        <strong>{{ overviewConfidence }}</strong>
        <p>{{ confidenceDescription }}</p>
      </article>
      <article class="overview-summary-card">
        <span>建议</span>
        <strong>{{ overviewRecommendation }}</strong>
        <p>结合实际情况再决策</p>
      </article>
    </div>

    <div class="overview-content-grid">
      <div class="overview-left-column">
        <section class="panel overview-check-panel">
          <h3>系统有没有认真检查？</h3>
          <p>这里展示简单对照、结果检查和反复优化记录。</p>
          <div class="overview-check-grid">
            <article v-for="item in overviewCheckItems" :key="item.label">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </article>
          </div>
          <div class="overview-badge-row">
            <span v-for="badge in overviewBadges" :key="badge">{{ badge }}</span>
          </div>
          <div v-if="targetSummaries.length" class="overview-badge-row">
            <span v-for="item in targetSummaries" :key="item.name">
              {{ item.name }}{{ item.metric ? ` · ${item.metric} ${item.value}` : '' }}
            </span>
          </div>
        </section>

        <section class="panel overview-factor-panel">
          <h3>影响结果的关键因素</h3>
          <p>{{ overviewFactorDescription }}</p>
          <div class="overview-factor-list">
            <div v-for="item in overviewFactors" :key="item.label" class="overview-factor-row">
              <strong>{{ item.label }}</strong>
              <div><span :style="{ width: `${item.percent}%` }"></span></div>
              <small>{{ item.percent }}%</small>
            </div>
            <p v-if="!overviewFactors.length" class="muted">当前任务没有返回真实特征重要性或诊断因素。</p>
          </div>
        </section>
      </div>

      <aside class="panel overview-explain-panel">
        <h3>结果怎么理解？</h3>
        <p>完成建模后，这里会展示最重要的指标和可读解释。</p>
        <div v-if="hasOverviewChart" class="overview-mini-chart">
          <svg viewBox="0 0 100 80" role="img" aria-label="结果趋势图">
            <polyline :points="overviewChartPoints" fill="none" stroke="#2563eb" stroke-width="2.2" />
            <polyline :points="overviewChartPointsAlt" fill="none" stroke="#0f8b8d" stroke-width="2.2" />
          </svg>
        </div>
        <p v-else class="muted">当前任务没有返回可绘制的真实预测对比点。</p>
        <div class="overview-insight">
          {{ explanationText }}
        </div>
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
