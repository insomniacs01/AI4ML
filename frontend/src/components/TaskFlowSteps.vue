<script setup>
import { computed } from 'vue'

const props = defineProps({
  currentStep: { type: Number, default: 1 },
})

const steps = [
  { index: 1, label: '填写任务' },
  { index: 2, label: '上传数据' },
  { index: 3, label: '工作台运行' },
  { index: 4, label: '查看结果' },
]

const normalizedStep = computed(() => Math.min(4, Math.max(1, Number(props.currentStep) || 1)))

function stepClass(step) {
  return {
    active: step.index === normalizedStep.value,
    done: step.index < normalizedStep.value,
  }
}
</script>

<template>
  <div class="task-flow-steps" aria-label="任务流程">
    <article
      v-for="step in steps"
      :key="step.index"
      :class="stepClass(step)"
      :aria-current="step.index === normalizedStep ? 'step' : undefined"
    >
      <strong>{{ step.index }}</strong>
      <span>{{ step.label }}</span>
    </article>
  </div>
</template>
