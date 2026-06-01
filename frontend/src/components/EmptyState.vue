<script setup>
import { Inbox } from 'lucide-vue-next'

defineProps({
  title: { type: String, default: '暂无数据' },
  description: { type: String, default: '稍后刷新或创建新的内容。' },
})
</script>

<template>
  <div class="empty-state">
    <Inbox :size="32" />
    <strong>{{ title }}</strong>
    <span>{{ description }}</span>
  </div>
</template>
