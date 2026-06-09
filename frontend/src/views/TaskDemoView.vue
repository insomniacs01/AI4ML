<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import DemoInputForm from '@/components/DemoInputForm.vue'
import { getDelivery, predict } from '@/api/taskPredictionDemo'

const props = defineProps({ taskId: { type: String, required: true } })
const router = useRouter()
const delivery = ref(null)
const result = ref('')
const error = ref('')
const loading = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    delivery.value = await getDelivery(props.taskId)
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
    const data = await predict(props.taskId, rows)
    result.value = JSON.stringify(data, null, 2)
  } catch (err) {
    error.value = err.message
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="模型在线演示" :description="taskId">
    <template #actions>
      <button class="secondary-action" type="button" @click="router.push(`/tasks/${taskId}`)">
        <ArrowLeft :size="18" />返回任务
      </button>
    </template>
  </PageHeader>

  <p v-if="error" class="form-error">{{ error }}</p>
  <section class="split-grid">
    <div class="panel form-stack">
      <div class="panel-title"><span>输入样本</span></div>
      <p class="muted">必填特征：{{ (delivery?.required_features || []).join('、') || '加载中' }}</p>
      <DemoInputForm :delivery="delivery" :disabled="loading" @submit="run" />
    </div>
    <div class="panel readable">
      <div class="panel-title"><span>预测结果</span></div>
      <pre>{{ result || '等待预测。' }}</pre>
    </div>
  </section>
</template>
