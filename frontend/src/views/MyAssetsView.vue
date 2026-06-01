<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ClipboardList, FileText } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import EmptyState from '@/components/EmptyState.vue'
import MetricCard from '@/components/MetricCard.vue'
import { getMyAssets } from '@/api/client'
import { modelDisplayName } from '@/utils/modelProfile'

const assets = ref({ prompts: [], plans: [] })
const error = ref('')
const loading = ref(false)

const totalCount = computed(() => (assets.value.prompts?.length || 0) + (assets.value.plans?.length || 0))

function assetLink(type, item) {
  const tab = type === 'plan' ? 'plans' : 'prompts'
  const assetId = item.plan_id || item.prompt_id || item.asset_id || ''
  return { path: '/community', query: { tab, asset_id: assetId } }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    assets.value = await getMyAssets()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="社区资产" description="这里展示当前账号发布到社区的提示词和执行方案。" />
  <p v-if="error" class="form-error">{{ error }}</p>

  <section class="metric-grid">
    <MetricCard label="资产总数" :value="totalCount" />
    <MetricCard label="提示词" :value="assets.prompts?.length || 0" />
    <MetricCard label="执行方案" :value="assets.plans?.length || 0" />
  </section>

  <EmptyState
    v-if="!loading && totalCount === 0"
    title="暂无社区资产"
    description="在任务详情页发布提示词或执行方案后，会出现在这里。"
  />

  <section v-if="totalCount" class="asset-section-grid">
    <div class="panel">
      <div class="panel-title"><span><FileText :size="18" /> 我的提示词</span></div>
      <div class="profile-asset-list">
        <RouterLink v-for="item in assets.prompts" :key="item.prompt_id" :to="assetLink('prompt', item)">
          <strong>提示词</strong><span>{{ item.name }}</span>
        </RouterLink>
        <EmptyState v-if="!assets.prompts?.length" title="暂无提示词" description="发布提示词后会展示在这里。" />
      </div>
    </div>

    <div class="panel">
      <div class="panel-title"><span><ClipboardList :size="18" /> 我的执行方案</span></div>
      <div class="profile-asset-list">
        <RouterLink v-for="item in assets.plans" :key="item.plan_id" :to="assetLink('plan', item)">
          <strong>执行方案</strong><span>{{ item.name }}</span>
        </RouterLink>
        <EmptyState v-if="!assets.plans?.length" title="暂无执行方案" :description="`发布 ${modelDisplayName} 方案后会展示在这里。`" />
      </div>
    </div>
  </section>
</template>
