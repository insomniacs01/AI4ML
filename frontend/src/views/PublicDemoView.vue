<script setup>
import { onMounted, ref } from 'vue'
import PageHeader from '@/components/PageHeader.vue'
import DemoInputForm from '@/components/DemoInputForm.vue'
import { getPublicDemo, predictPublicDemo } from '@/api/taskPredictionDemo'

const props = defineProps({ deploymentId: { type: String, required: true } })
const delivery = ref(null)
const result = ref('')
const error = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    delivery.value = await getPublicDemo(props.deploymentId)
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

async function run(rows) {
  error.value = ''
  result.value = ''
  try {
    const data = await predictPublicDemo(props.deploymentId, rows)
    result.value = JSON.stringify(data, null, 2)
  } catch (err) {
    error.value = err.message
  }
}

onMounted(load)
</script>

<template>
  <main class="public-demo-page">
    <PageHeader title="公开模型演示" :description="deploymentId" />

    <p v-if="error" class="form-error">{{ error }}</p>
    <section class="public-demo-layout">
      <div class="panel form-stack">
        <div class="panel-title"><span>输入样本</span></div>
        <p class="muted">必填特征：{{ (delivery?.required_features || []).join('、') || '加载中' }}</p>
        <DemoInputForm :delivery="delivery" :disabled="loading" @submit="run" />
      </div>
      <div class="panel readable result-panel">
        <div class="panel-title"><span>预测结果</span></div>
        <pre>{{ result || '等待预测。' }}</pre>
      </div>
    </section>
  </main>
</template>
