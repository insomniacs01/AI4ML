<script setup>
import DemoInputForm from '@/components/DemoInputForm.vue'

defineProps({
  delivery: { type: Object, default: null },
  readOnlyMode: { type: Boolean, default: false },
  predictionLoading: { type: Boolean, default: false },
  predictionError: { type: String, default: '' },
  predictionStatusText: { type: String, required: true },
  predictionResult: { type: Object, default: null },
  predictionResultLabel: { type: String, required: true },
  predictionResultValue: { type: String, required: true },
  predictionResultNote: { type: String, required: true },
})

defineEmits(['predict'])
</script>

<template>
  <section class="prediction-workspace">
    <div class="panel prediction-input-panel">
      <div class="prediction-panel-head">
        <div>
          <span class="panel-eyebrow">PREDICT</span>
          <h3>预测输入</h3>
          <p>编辑一条或多条样本后运行真实模型预测。字段值会按当前模型入口提交。</p>
        </div>
      </div>
      <div class="feature-chip-list">
        <span v-for="feature in (delivery?.required_features || [])" :key="feature">{{ feature }}</span>
        <span v-if="!(delivery?.required_features || []).length">暂无输入字段清单</span>
      </div>
      <DemoInputForm :delivery="delivery" :disabled="readOnlyMode" :submitting="predictionLoading" @submit="$emit('predict', $event)" />
    </div>

    <section class="panel prediction-result-panel">
      <div class="prediction-panel-head compact">
        <div>
          <span class="panel-eyebrow">RESULT</span>
          <h3>预测结果</h3>
        </div>
        <span class="prediction-status-pill" :class="{ loading: predictionLoading, error: predictionError }">{{ predictionStatusText }}</span>
      </div>
      <div v-if="predictionLoading" class="prediction-state">
        <span class="loading-spinner"></span>
        <strong>正在调用当前任务的真实模型预测...</strong>
      </div>
      <div v-else-if="predictionResult" class="prediction-value-card">
        <span>{{ predictionResultLabel }}</span>
        <strong>{{ predictionResultValue }}</strong>
        <p>{{ predictionResultNote }}</p>
      </div>
      <div v-else-if="predictionError" class="prediction-state error">
        <strong>{{ predictionError }}</strong>
      </div>
      <div v-else class="prediction-state">
        <strong>运行预测后，结果会显示在这里。</strong>
      </div>
    </section>
  </section>
</template>
