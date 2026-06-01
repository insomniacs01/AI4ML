<script setup>
import { taskStatusLabel } from '@/utils/labels'

const props = defineProps({
  status: { type: String, default: '' },
})

function label(status) {
  const workflowMap = {
    pending: '待处理',
    approved: '已通过',
    rejected: '已拒绝',
    unknown: '未同步',
  }
  return workflowMap[status] || taskStatusLabel(status) || '未同步'
}
</script>

<template>
  <span class="status-badge" :class="`status-${props.status || 'unknown'}`">{{ label(props.status) }}</span>
</template>
