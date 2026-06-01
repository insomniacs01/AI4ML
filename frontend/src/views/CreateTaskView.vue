<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Brain, ClipboardList, FileText, UploadCloud, X } from 'lucide-vue-next'
import PageHeader from '@/components/PageHeader.vue'
import { createTask, getPlanDetail, getPlans, getPromptDetail, getPrompts, uploadDataset } from '@/api/client'
import { modelDisplayName } from '@/utils/modelProfile'

const router = useRouter()
const route = useRoute()
const submitting = ref(false)
const showAdvanced = ref(false)
const error = ref('')
const uploadedDataset = ref(null)
const selectedPrompt = ref(null)
const selectedPlan = ref(null)
const communityPrompts = ref([])
const communityPlans = ref([])
const form = ref({
  title: '',
  requirement: '请帮我基于这份表格数据训练一个预测模型，并输出业务可读的模型性能和特征重要性解释。',
  dataset_path: '',
  dataset_file: null,
  target_column: '',
  task_type: '',
  metric: '',
  time_budget_s: 20,
  time_column: '',
  forecast_horizon: 3,
  series_id_column: '',
  image_label_mode: 'subdir',
  use_llm: true,
  enable_tools: true,
  enable_hitl: true,
  hitl_auto_approve: false,
  enable_react: true,
  feature_drop: '',
  selected_plan_text: '',
  selected_plan_id: '',
  selected_plan_name: '',
})

const hasDataset = computed(() => Boolean(form.value.dataset_file || form.value.dataset_path.trim()))
const canSubmit = computed(() => form.value.requirement.trim() && hasDataset.value)
const currentTaskType = computed(() => form.value.task_type || '')
const uploadedDatasetLabel = computed(() => form.value.dataset_file?.name || '')

function setFile(event) {
  form.value.dataset_file = event.target.files?.[0] || null
  form.value.dataset_path = ''
  uploadedDataset.value = null
}

async function ensureDatasetUploaded() {
  if (form.value.dataset_path) return form.value.dataset_path
  if (!form.value.dataset_file) throw new Error('请先上传表格文件或图像压缩包')
  const fd = new FormData()
  fd.append('dataset_file', form.value.dataset_file)
  uploadedDataset.value = await uploadDataset(fd)
  form.value.dataset_path = uploadedDataset.value.dataset_path
  return form.value.dataset_path
}

async function submit() {
  submitting.value = true
  error.value = ''
  try {
    const fd = new FormData()
    Object.entries(form.value).forEach(([key, value]) => {
      if (key === 'dataset_file' || key === 'title') return
      if (value !== null && value !== undefined && value !== '') fd.append(key, String(value))
    })
    if (form.value.title.trim()) {
      fd.set('requirement', `${form.value.title.trim()}\n\n${form.value.requirement.trim()}`)
    }
    const datasetPath = await ensureDatasetUploaded()
    if (datasetPath) fd.set('dataset_path', datasetPath)
    else fd.delete('dataset_path')
    fd.set('use_llm', String(form.value.use_llm))
    fd.set('enable_tools', String(form.value.enable_tools))
    fd.set('enable_hitl', String(form.value.enable_hitl))
    fd.set('hitl_auto_approve', String(form.value.hitl_auto_approve))
    fd.set('enable_react', String(form.value.enable_react))

    const data = await createTask(fd)
    const target = `/workspace`
    try {
      await router.push(target)
    } catch {
      window.location.assign(target)
    }
  } catch (err) {
    error.value = err.message
  } finally {
    submitting.value = false
  }
}

function applyPrompt(prompt) {
  selectedPrompt.value = prompt
  if (prompt.prompt_title) form.value.title = prompt.prompt_title
  else if (prompt.name) form.value.title = prompt.name
  if (prompt.prompt_description) form.value.requirement = prompt.prompt_description
  else if (prompt.description) form.value.requirement = prompt.description
  if (prompt.target_column) form.value.target_column = prompt.target_column
  if (prompt.task_category) form.value.task_type = prompt.task_category
  if (prompt.metric) form.value.metric = prompt.metric
}

function applyPlan(plan) {
  selectedPlan.value = plan
  form.value.selected_plan_text = plan.plan_text || ''
  form.value.selected_plan_id = plan.plan_id || plan.asset_id || ''
  form.value.selected_plan_name = plan.name || ''
  showAdvanced.value = true
}

function clearPrompt() {
  selectedPrompt.value = null
}

function clearPlan() {
  selectedPlan.value = null
  form.value.selected_plan_text = ''
  form.value.selected_plan_id = ''
  form.value.selected_plan_name = ''
}

function selectPromptById(promptId) {
  const prompt = communityPrompts.value.find((item) => item.prompt_id === promptId)
  if (prompt) applyPrompt(prompt)
}

function selectPlanById(planId) {
  const plan = communityPlans.value.find((item) => item.plan_id === planId)
  if (plan) applyPlan(plan)
  else clearPlan()
}

async function loadRoutePrompt() {
  const promptId = String(route.query.prompt_id || '').trim()
  if (!promptId) return
  try {
    applyPrompt(await getPromptDetail(promptId))
  } catch (err) {
    error.value = err.message
  }
}

async function loadRoutePlan() {
  const planId = String(route.query.plan_id || '').trim()
  if (!planId) return
  try {
    applyPlan(await getPlanDetail(planId))
  } catch (err) {
    error.value = err.message
  }
}

async function loadRouteInputs() {
  try {
    const [promptData, planData] = await Promise.all([getPrompts(false), getPlans(false)])
    communityPrompts.value = promptData.items || []
    communityPlans.value = planData.items || []
  } catch (err) {
    communityPrompts.value = []
    communityPlans.value = []
    error.value = `社区提示词和方案暂时不可用：${err.message}`
  }
  await loadRoutePrompt()
  await loadRoutePlan()
}

onMounted(loadRouteInputs)
</script>

<template>
  <PageHeader title="开始任务" description="填写任务主题、描述信息并上传数据集，AI 会先理解需求，再进入工作台执行。" />

  <section class="start-task-shell">
    <div class="start-task-steps" aria-label="任务流程">
      <article class="active">
        <strong>1</strong>
        <span>填写任务</span>
      </article>
      <article :class="{ active: hasDataset }">
        <strong>2</strong>
        <span>上传数据</span>
      </article>
      <article>
        <strong>3</strong>
        <span>AI 自动尝试</span>
      </article>
      <article>
        <strong>4</strong>
        <span>查看结果</span>
      </article>
    </div>

    <div class="start-task-layout">
      <section class="panel start-task-card">
        <p v-if="error" class="form-error">{{ error }}</p>
        <div v-if="selectedPrompt" class="insight-box">
          <FileText :size="18" />
          <span>已导入提示词：{{ selectedPrompt.name }}</span>
          <button class="icon-button subtle" type="button" title="清除提示词" @click="clearPrompt"><X :size="16" /></button>
        </div>
        <div v-if="selectedPlan" class="insight-box">
          <ClipboardList :size="18" />
          <span>已选择执行方案：{{ selectedPlan.name }}</span>
          <button class="icon-button subtle" type="button" title="清除方案" @click="clearPlan"><X :size="16" /></button>
        </div>

        <div v-if="communityPrompts.length" class="start-task-secondary">
          <label class="field">
            <span>从提示词广场导入</span>
            <select :value="selectedPrompt?.prompt_id || ''" @change="selectPromptById($event.target.value)">
              <option value="">不使用提示词</option>
              <option v-for="item in communityPrompts" :key="item.prompt_id" :value="item.prompt_id">
                {{ item.name }}
              </option>
            </select>
          </label>
        </div>

        <label class="field start-task-field">
          <span>主题</span>
          <input v-model="form.title" placeholder="例如：预测产量、识别流失客户、分类图像样本" />
        </label>

        <label class="field start-task-field">
          <span>描述信息</span>
          <textarea
            v-model="form.requirement"
            rows="6"
            placeholder="描述你希望 AI 完成的预测、分析、建模或报告任务。目标可以是单个或多个，也可以不写字段名。"
          />
        </label>

        <label class="upload-zone start-upload-zone">
          <UploadCloud :size="28" />
          <strong>{{ uploadedDatasetLabel || '点击上传数据集' }}</strong>
          <span>支持 CSV 或 ZIP 文件，大小不超过 200MB。</span>
          <input type="file" accept=".csv,.zip" @change="setFile" />
        </label>

        <button class="secondary-action full" type="button" @click="showAdvanced = !showAdvanced">
          {{ showAdvanced ? '收起高级设置' : '高级设置' }}
        </button>

        <div v-if="showAdvanced" class="form-stack start-advanced">
          <label v-if="communityPlans.length" class="field">
            <span>使用方案广场方案</span>
            <select :value="selectedPlan?.plan_id || ''" @change="selectPlanById($event.target.value)">
              <option value="">不使用社区方案</option>
              <option v-for="item in communityPlans" :key="item.plan_id" :value="item.plan_id">
                {{ item.name }}
              </option>
            </select>
          </label>
          <label v-if="selectedPlan || form.selected_plan_text" class="field">
            <span>执行方案</span>
            <textarea
              v-model="form.selected_plan_text"
              rows="8"
              :placeholder="`选择或粘贴已确认的 ${modelDisplayName} 执行方案。创建任务后会直接交给 ${modelDisplayName} 执行，跳过重新规划。`"
            />
          </label>
          <div class="inline-fields">
            <label class="field">
              <span>目标列</span>
              <input v-model="form.target_column" placeholder="留空则自动推断" />
            </label>
            <label class="field">
              <span>任务类型</span>
              <select v-model="form.task_type">
                <option value="">自动推断</option>
                <option value="classification">表格分类</option>
                <option value="regression">表格回归</option>
                <option value="time_series_forecasting">时间序列预测</option>
                <option value="image_classification">图像分类</option>
              </select>
            </label>
          </div>
          <div v-if="currentTaskType === 'time_series_forecasting'" class="inline-fields">
            <label class="field">
              <span>时间列</span>
              <input v-model="form.time_column" placeholder="date / ds / 时间" />
            </label>
            <label class="field">
              <span>预测步长</span>
              <input v-model.number="form.forecast_horizon" type="number" min="1" max="365" />
            </label>
          </div>
          <label v-if="currentTaskType === 'time_series_forecasting'" class="field">
            <span>序列 ID 列（可选）</span>
            <input v-model="form.series_id_column" placeholder="第一阶段可留空，默认单序列" />
          </label>
          <label v-if="currentTaskType === 'image_classification'" class="field">
            <span>图像标签方式</span>
            <select v-model="form.image_label_mode">
              <option value="subdir">按子目录名作为标签</option>
            </select>
          </label>
          <div class="inline-fields">
            <label class="field">
              <span>优化指标</span>
              <input v-model="form.metric" placeholder="自动选择" />
            </label>
            <label class="field">
              <span>时间预算（秒）</span>
              <input v-model.number="form.time_budget_s" type="number" min="5" />
            </label>
          </div>
          <label class="field">
            <span>忽略特征</span>
            <input v-model="form.feature_drop" placeholder="id, name" />
          </label>
          <div class="toggle-grid">
            <label><input v-model="form.enable_tools" type="checkbox" /> 工具检查</label>
            <label><input v-model="form.enable_hitl" type="checkbox" /> 人工确认</label>
            <label><input v-model="form.enable_react" type="checkbox" /> 自动迭代</label>
          </div>
        </div>

        <button class="primary-action start-submit" type="button" :disabled="!canSubmit || submitting" @click="submit">
          {{ submitting ? '创建中' : '让 AI 先理解我的需求' }}
          <ArrowRight :size="18" />
        </button>
      </section>

      <aside class="panel start-next-card">
        <strong>下一步</strong>
        <div class="start-next-icon">
          <Brain :size="30" />
        </div>
        <p>上传数据后，AI 会先帮你确认要预测什么、适合怎么建模。</p>
        <div>
          <strong>不用担心</strong>
          <span>我们会一步步帮你完成建模。</span>
        </div>
      </aside>
    </div>
  </section>

  <div v-if="submitting" class="submit-overlay">
    <div class="submit-card">
      <span class="submit-spinner"></span>
      <strong>正在创建任务</strong>
      <p>正在上传数据并初始化智能体流程</p>
    </div>
  </div>
</template>
