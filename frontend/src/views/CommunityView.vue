<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ClipboardList, CopyPlus, FileText, GitFork, RefreshCw, Search, X } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import LoadingBlock from '@/components/LoadingBlock.vue'
import StatusBadge from '@/components/StatusBadge.vue'
import {
  forkPlan,
  getCommunityAssets,
  getPlanDetail,
  getPromptDetail,
} from '@/api/community'
import { optionalLoad } from '@/utils/async'
import { assetIdForItem, assetIntro, assetTypeForItem, assetTypeLabel, searchableAssetText } from '@/utils/communityAssets'
import { modelDisplayName } from '@/utils/modelProfile'

const router = useRouter()
const route = useRoute()
const active = ref('prompts')
const query = ref('')
const prompts = ref([])
const plans = ref([])
const selectedAsset = ref(null)
const loading = ref(false)
const detailLoading = ref(false)
const error = ref('')
const message = ref('')
const assetDetails = new Map()
let assetDetailRequestId = 0

const currentItems = computed(() => {
  const source = active.value === 'plans' ? plans.value : prompts.value
  const q = query.value.trim().toLowerCase()
  if (!q) return source
  return source.filter((item) => searchableAssetText(item).includes(q))
})

function itemIntro(item) {
  return assetIntro(item, 120)
}

function applyRouteSelection() {
  const tab = String(route.query.tab || '')
  if (['prompts', 'plans'].includes(tab)) active.value = tab
  const assetId = String(route.query.asset_id || '')
  if (!assetId) return
  const collection = active.value === 'plans' ? plans.value : prompts.value
  const item = collection.find((asset) => assetIdForItem(asset) === assetId)
  if (item) selectAsset(item)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const assets = await optionalLoad(() => getCommunityAssets(false), { prompts: [], plans: [] })
    prompts.value = assets.prompts || []
    plans.value = assets.plans || []
    applyRouteSelection()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

const selectedAssetReady = computed(() => Boolean(selectedAsset.value?.loaded))

async function selectAsset(item) {
  const type = assetTypeForItem(item)
  const assetId = assetIdForItem(item)
  const requestId = ++assetDetailRequestId
  error.value = ''
  const cacheKey = `${type}:${assetId}`
  const cached = assetDetails.get(cacheKey)
  selectedAsset.value = { type, item: cached || item, loaded: Boolean(cached) }
  if (cached || !assetId) {
    detailLoading.value = false
    return
  }
  detailLoading.value = true
  try {
    const detail = type === 'plan' ? await getPlanDetail(assetId) : await getPromptDetail(assetId)
    assetDetails.set(cacheKey, detail)
    if (requestId === assetDetailRequestId) {
      selectedAsset.value = { type, item: detail, loaded: true }
    }
  } catch (err) {
    if (requestId === assetDetailRequestId) error.value = err.message
  } finally {
    if (requestId === assetDetailRequestId) detailLoading.value = false
  }
}

async function copyText(value, successMessage) {
  const text = String(value || '').trim()
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    message.value = successMessage
  } catch {
    error.value = '复制失败，请手动选中文本复制。'
  }
}

function usePrompt(item) {
  router.push({
    path: '/create',
    query: {
      prompt_id: item.prompt_id,
    },
  })
}

function usePlan(item) {
  router.push({
    path: '/create',
    query: {
      plan_id: item.plan_id,
    },
  })
}

async function forkSelectedPlan(item) {
  try {
    const forked = await forkPlan(item.plan_id)
    message.value = '方案已复制到你的资产中'
    await load()
    return forked
  } catch (err) {
    error.value = err.message
    return null
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="社区广场" :description="`复用团队沉淀的任务提示词和 ${modelDisplayName} 执行方案。`">
    <template #actions>
      <button class="secondary-action refresh-action" type="button" :disabled="loading" @click="load">
        <RefreshCw :class="{ spinning: loading }" :size="18" />刷新
      </button>
    </template>
  </PageHeader>

  <p v-if="error" class="form-error">{{ error }}</p>
  <p v-if="message" class="form-success">{{ message }}</p>

  <LoadingBlock v-if="loading" />

  <template v-else>
    <section class="community-market-panel">
      <div class="community-market-head">
        <div class="community-market-copy">
          <h2>提示词 / 方案广场</h2>
          <p>列表展示已经发布到社区广场的任务提示词和 {{ modelDisplayName }} 执行方案；点击条目查看详情并复用到新任务。</p>
        </div>

        <div class="community-market-controls">
          <label class="search-box community-search-box">
            <Search :size="17" />
            <input v-model="query" placeholder="搜索名称或描述" />
          </label>
          <div class="community-tab-group" role="tablist" aria-label="社区资产类型">
            <button
              :class="{ active: active === 'prompts' }"
              type="button"
              role="tab"
              :aria-selected="active === 'prompts'"
              @click="active = 'prompts'; selectedAsset = null"
            >
              <span>提示词广场</span>
              <strong>{{ prompts.length }}</strong>
            </button>
            <button
              :class="{ active: active === 'plans' }"
              type="button"
              role="tab"
              :aria-selected="active === 'plans'"
              @click="active = 'plans'; selectedAsset = null"
            >
              <span>方案广场</span>
              <strong>{{ plans.length }}</strong>
            </button>
          </div>
        </div>
      </div>

      <div class="community-list-shell">
        <div v-if="currentItems.length === 0" class="community-empty-note">
          当前筛选条件下还没有资产记录。任务详情页发布提示词或执行方案后，会出现在这里。
        </div>
        <div v-else class="community-list">
          <button
            v-for="item in currentItems"
            :key="assetIdForItem(item)"
            class="community-list-row"
            type="button"
            :class="{ selected: selectedAsset && assetIdForItem(selectedAsset.item) === assetIdForItem(item) }"
            @click="selectAsset(item)"
          >
            <span class="asset-icon community-row-icon">
              <ClipboardList v-if="assetTypeForItem(item) === 'plan'" :size="20" />
              <FileText v-else :size="20" />
            </span>
            <span class="community-row-main">
              <span class="community-row-title">
                <h3>{{ item.name }}</h3>
                <StatusBadge v-if="item.status" :status="item.status" />
              </span>
              <p class="asset-description">{{ itemIntro(item) }}</p>
              <div class="asset-type-line">{{ assetTypeLabel(assetTypeForItem(item)) }}</div>
            </span>
            <span class="community-row-action">查看详情</span>
          </button>
        </div>
      </div>
    </section>

    <section v-if="selectedAsset" class="panel community-detail-panel asset-detail-panel">
      <div class="panel-title">
        <span>{{ assetTypeLabel(selectedAsset.type) }}详情</span>
        <button class="icon-button subtle" type="button" @click="selectedAsset = null"><X :size="18" /></button>
      </div>
      <h3>{{ selectedAsset.item.name }}</h3>
      <p class="muted">{{ selectedAsset.item.description || itemIntro(selectedAsset.item) }}</p>

      <template v-if="selectedAsset.type === 'prompt'">
        <div class="divider-line"></div>
        <label class="field">
          <span>主题</span>
          <input :value="selectedAsset.item.prompt_title || selectedAsset.item.name" readonly />
        </label>
        <label class="field">
          <span>描述信息</span>
          <textarea :value="selectedAsset.item.prompt_description || selectedAsset.item.description" rows="8" readonly />
        </label>
        <div class="form-actions">
          <button class="primary-action" type="button" :disabled="!selectedAssetReady" @click="usePrompt(selectedAsset.item)">用此提示词开始任务</button>
          <button class="secondary-action" type="button" :disabled="!selectedAssetReady" @click="copyText(`${selectedAsset.item.prompt_title || selectedAsset.item.name}\n\n${selectedAsset.item.prompt_description || selectedAsset.item.description || ''}`, '提示词已复制')">
            <CopyPlus :size="17" />复制提示词
          </button>
        </div>
      </template>

      <template v-else>
        <div class="divider-line"></div>
        <label class="field">
          <span>{{ modelDisplayName }} 执行方案</span>
          <textarea :value="selectedAsset.item.plan_text || ''" rows="14" readonly />
        </label>
        <LoadingBlock v-if="detailLoading" />
        <div class="form-actions">
          <button class="primary-action" type="button" :disabled="!selectedAssetReady" @click="usePlan(selectedAsset.item)">用此方案开始任务</button>
          <button class="secondary-action" type="button" :disabled="!selectedAssetReady" @click="forkSelectedPlan(selectedAsset.item)">
            <GitFork :size="17" />复制方案
          </button>
          <button class="secondary-action" type="button" :disabled="!selectedAssetReady" @click="copyText(selectedAsset.item.plan_text, '方案已复制')">
            <CopyPlus :size="17" />复制文本
          </button>
        </div>
      </template>
    </section>
  </template>
</template>
