<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { CheckCircle2, FileText, RefreshCw, X } from 'lucide-vue-next'
import { submitHitl } from '@/api/client'
import { renderMarkdown } from '@/utils/markdown'
import { modelDisplayName } from '@/utils/modelProfile'

const props = defineProps({
  open: { type: Boolean, default: false },
  taskId: { type: String, required: true },
  hitl: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  loadError: { type: String, default: '' },
})

const emit = defineEmits(['close', 'submitted'])

const busy = ref(false)
const error = ref('')
const planViewMode = ref('preview')

const requirementForm = reactive({
  requirement_notes: '',
})
const dataForm = reactive({
  label_column: '',
  problem_type: '',
  metric_name: '',
})
const featureForm = reactive({
  include_columns: '',
  exclude_columns: '',
})
const modelForm = reactive({
  allowed_models: '',
  excluded_models: '',
})
const trainingForm = reactive({
  time_limit: '',
  cv_folds: '',
  metric_name: '',
})
const reportForm = reactive({
  report_focus: '',
})
const codexPlanForm = reactive({
  plan_text: '',
})
const improvementPlanForm = reactive({
  plan_text: '',
})

const requestPayload = computed(() => props.hitl?.request || {})
const isCodexPlanApproval = computed(() => requestPayload.value.request_type === 'codex_plan_approval')
const isCodexImprovementReview = computed(() => requestPayload.value.request_type === 'codex_improvement_review')
const stage = computed(() => normalizeStage(requestPayload.value.stage || props.hitl?.approval?.stage || 'training_validation'))
const stageMeta = computed(() => {
  if (isCodexImprovementReview.value) {
    return {
      title: '确认是否继续改进',
      description: `${modelDisplayName.value} 已生成改进决策方案。请选择继续改进，或停止改进并直接生成当前结果报告。`,
      defaultAction: '选择继续改进或停止并生成报告',
    }
  }
  if (isCodexPlanApproval.value) {
    return {
      title: `确认 ${modelDisplayName.value} 建模计划`,
      description: `${modelDisplayName.value} 已完成数据理解并生成计划。你可以直接确认执行，也可以编辑计划后确认，或要求 ${modelDisplayName.value} 重新生成计划。`,
      defaultAction: '确认计划并执行',
    }
  }
  const map = {
    requirement_analysis: {
      title: '需求分析确认',
      description: '确认本次实验目标是否清楚，必要时补充业务口径或约束。',
      defaultAction: '确认需求后继续',
    },
    data_analysis: {
      title: '数据分析确认',
      description: '确认目标列、任务类型和评价指标是否符合本次建模目标。',
      defaultAction: '确认数据理解后继续',
    },
    feature_engineering: {
      title: '特征工程确认',
      description: '确认需要保留或排除的特征列，再继续后续建模。',
      defaultAction: '确认特征处理后继续',
    },
    model_selection: {
      title: '模型选择确认',
      description: '确认候选模型范围，限制不希望使用的模型。',
      defaultAction: '确认模型范围后继续',
    },
    training_validation: {
      title: '训练验证确认',
      description: '确认训练预算、交叉验证折数和优化指标后继续。',
      defaultAction: '确认训练设置后继续',
    },
    report_generation: {
      title: '报告生成确认',
      description: '确认报告重点，决定最终报告需要突出哪些业务结论。',
      defaultAction: '确认报告重点后继续',
    },
  }
  return map[stage.value] || map.training_validation
})
const requestTitle = computed(() => requestPayload.value.title || stageMeta.value.title)
const requestDescription = computed(() => requestPayload.value.summary || stageMeta.value.description)
const suggestedAction = computed(() => requestPayload.value.suggested_action || requestPayload.value.default_action || stageMeta.value.defaultAction)
const parameterDefaults = computed(() => requestPayload.value.parameters || requestPayload.value.details?.parameters || {})
const riskNotes = computed(() => requestPayload.value.risk_notes || props.hitl?.risk_notes || [])
const submittingDisabled = computed(() => busy.value || props.loading || Boolean(props.loadError))
const renderedCodexPlan = computed(() => renderMarkdown(codexPlanForm.plan_text || `等待 ${modelDisplayName.value} 写入 output/plan.md`))
const renderedImprovementPlan = computed(() => renderMarkdown(improvementPlanForm.plan_text || '等待 Codex 写入 output/improvement_plan.md'))
const advisorSummary = computed(() => {
  const diagnosis = requestPayload.value.advisor_diagnosis
  if (!diagnosis || typeof diagnosis !== 'object') return ''
  return diagnosis.summary || diagnosis.root_cause || diagnosis.recommendation || ''
})

function normalizeStage(value) {
  return {
    request_verification: 'data_analysis',
    code_verification: 'feature_engineering',
    execution_verification: 'training_validation',
    request_review: 'requirement_analysis',
    code_generation: 'feature_engineering',
    execution_validation: 'training_validation',
    report_review: 'report_generation',
  }[value] || value || 'training_validation'
}

function csv(value) {
  const raw = Array.isArray(value) ? value : String(value || '').split(',')
  return raw.map((item) => String(item).trim()).filter(Boolean)
}

function csvText(value) {
  if (Array.isArray(value)) return value.join(', ')
  return String(value || '')
}

function setIfChanged(result, key, value, baseline, cast = null) {
  if (value === '' || value === null || value === undefined) return
  let next = value
  if (cast === 'number') next = Number(value)
  if (cast === 'csv') next = csv(value)
  if (JSON.stringify(next) !== JSON.stringify(baseline?.[key])) result[key] = next
}

function resetForms() {
  error.value = ''
  planViewMode.value = 'preview'
  const spec = props.hitl?.task_spec || requestPayload.value.task_spec || {}
  const plan = props.hitl?.train_plan || requestPayload.value.train_plan || {}
  const parameters = parameterDefaults.value
  codexPlanForm.plan_text = requestPayload.value.plan_text || requestPayload.value.details?.plan_text || ''
  improvementPlanForm.plan_text = requestPayload.value.improvement_plan_text || requestPayload.value.details?.improvement_plan_text || ''

  requirementForm.requirement_notes = csvText(parameters.requirement_notes || parameters.notes)
  dataForm.label_column = parameters.label_column || spec.target_column || ''
  dataForm.problem_type = parameters.problem_type || spec.task_type || ''
  dataForm.metric_name = parameters.metric_name || spec.metric || ''
  featureForm.include_columns = csvText(parameters.include_columns)
  featureForm.exclude_columns = csvText(parameters.exclude_columns)
  modelForm.allowed_models = csvText(parameters.allowed_models)
  modelForm.excluded_models = csvText(parameters.excluded_models)
  trainingForm.time_limit = parameters.time_limit ?? plan.time_budget_s ?? spec.time_budget_s ?? ''
  trainingForm.cv_folds = parameters.cv_folds ?? ''
  trainingForm.metric_name = parameters.metric_name || spec.metric || plan.metric || ''
  reportForm.report_focus = csvText(parameters.report_focus)
}

function collectAdjustments() {
  const parameters = parameterDefaults.value
  const result = {}

  if (isCodexPlanApproval.value) {
    setIfChanged(result, 'plan_text', codexPlanForm.plan_text, parameters)
  } else if (isCodexImprovementReview.value) {
    setIfChanged(result, 'improvement_plan_text', improvementPlanForm.plan_text, parameters)
  } else if (stage.value === 'requirement_analysis') {
    setIfChanged(result, 'requirement_notes', requirementForm.requirement_notes, parameters, 'csv')
  } else if (stage.value === 'data_analysis') {
    setIfChanged(result, 'label_column', dataForm.label_column, parameters)
    setIfChanged(result, 'problem_type', dataForm.problem_type, parameters)
    setIfChanged(result, 'metric_name', dataForm.metric_name, parameters)
  } else if (stage.value === 'feature_engineering') {
    setIfChanged(result, 'include_columns', featureForm.include_columns, parameters, 'csv')
    setIfChanged(result, 'exclude_columns', featureForm.exclude_columns, parameters, 'csv')
  } else if (stage.value === 'model_selection') {
    setIfChanged(result, 'allowed_models', modelForm.allowed_models, parameters, 'csv')
    setIfChanged(result, 'excluded_models', modelForm.excluded_models, parameters, 'csv')
  } else if (stage.value === 'training_validation') {
    setIfChanged(result, 'time_limit', trainingForm.time_limit, parameters, 'number')
    setIfChanged(result, 'cv_folds', trainingForm.cv_folds, parameters, 'number')
    setIfChanged(result, 'metric_name', trainingForm.metric_name, parameters)
  } else if (stage.value === 'report_generation') {
    setIfChanged(result, 'report_focus', reportForm.report_focus, parameters, 'csv')
  }

  return result
}

async function submit(action) {
  busy.value = true
  error.value = ''
  try {
    const adjustments = action === 'retry' || isCodexPlanApproval.value ? collectAdjustments() : {}
    const data = await submitHitl(props.taskId, {
      action,
      adjustments: action === 'reject' ? {} : adjustments,
      plan_text: isCodexPlanApproval.value ? codexPlanForm.plan_text : null,
    })
    emit('submitted', data)
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

watch(() => [props.open, props.hitl], resetForms, { immediate: true })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @click.self="emit('close')">
      <section class="modal-panel hitl-modal" role="dialog" aria-modal="true" :aria-label="requestTitle">
        <div class="modal-head">
          <div>
            <p class="eyebrow">Human-in-the-loop</p>
            <h2>{{ requestTitle }}</h2>
            <p class="muted">{{ requestDescription }}</p>
          </div>
          <button class="icon-button subtle" type="button" :disabled="busy" title="关闭" @click="emit('close')">
            <X :size="18" />
          </button>
        </div>

        <p v-if="error || loadError" class="form-error">{{ error || loadError }}</p>

        <div v-if="loading" class="form-warning progress-alert">
          <RefreshCw class="spinning" :size="17" />
          <span>正在加载人工确认内容，请稍候。</span>
        </div>

        <div v-if="!loading" class="hitl-summary">
          <span>状态：{{ hitl?.status || requestPayload.status || '-' }}</span>
          <span>阶段：{{ requestPayload.stage_label || stageMeta.title }}</span>
          <span>建议动作：{{ suggestedAction }}</span>
        </div>

        <div v-if="!loading && isCodexImprovementReview" class="form-stack">
          <div class="field plan-review-field">
            <div class="plan-review-toolbar">
              <span>改进决策方案</span>
            </div>
            <article
              class="markdown-report plan-markdown-preview"
              v-html="renderedImprovementPlan"
            ></article>
          </div>
          <div v-if="advisorSummary" class="hitl-advisor-summary">
            <strong>顾问诊断</strong>
            <span>{{ advisorSummary }}</span>
          </div>
        </div>

        <div v-else-if="!loading && isCodexPlanApproval" class="form-stack">
          <div class="field plan-review-field">
            <div class="plan-review-toolbar">
              <span>{{ modelDisplayName }} 建模计划</span>
              <div class="plan-view-tabs" role="tablist" aria-label="计划显示方式">
                <button
                  type="button"
                  :class="{ active: planViewMode === 'preview' }"
                  :aria-selected="planViewMode === 'preview'"
                  role="tab"
                  @click="planViewMode = 'preview'"
                >
                  预览
                </button>
                <button
                  type="button"
                  :class="{ active: planViewMode === 'edit' }"
                  :aria-selected="planViewMode === 'edit'"
                  role="tab"
                  @click="planViewMode = 'edit'"
                >
                  编辑
                </button>
              </div>
            </div>
            <article
              v-if="planViewMode === 'preview'"
              class="markdown-report plan-markdown-preview"
              v-html="renderedCodexPlan"
            ></article>
            <textarea
              v-else
              v-model="codexPlanForm.plan_text"
              rows="16"
              :placeholder="`等待 ${modelDisplayName} 写入 output/plan.md`"
            />
          </div>
        </div>

        <div v-else-if="!loading && stage === 'requirement_analysis'" class="form-stack">
          <label class="field">
            <span>需求补充说明</span>
            <textarea v-model="requirementForm.requirement_notes" rows="3" placeholder="例如：优先解释业务影响、重点关注召回率" />
          </label>
        </div>

        <div v-else-if="!loading && stage === 'data_analysis'" class="form-stack">
          <div class="inline-fields compact-fields">
            <label class="field"><span>目标列</span><input v-model="dataForm.label_column" /></label>
            <label class="field">
              <span>任务类型</span>
              <select v-model="dataForm.problem_type">
                <option value="">保持当前</option>
                <option value="classification">表格分类</option>
                <option value="regression">表格回归</option>
              </select>
            </label>
            <label class="field"><span>评价指标</span><input v-model="dataForm.metric_name" placeholder="accuracy / f1 / rmse" /></label>
          </div>
        </div>

        <div v-else-if="!loading && stage === 'feature_engineering'" class="form-stack">
          <div class="inline-fields compact-fields">
            <label class="field"><span>保留特征列</span><input v-model="featureForm.include_columns" placeholder="age, income" /></label>
            <label class="field"><span>排除特征列</span><input v-model="featureForm.exclude_columns" placeholder="id, name" /></label>
          </div>
        </div>

        <div v-else-if="!loading && stage === 'model_selection'" class="form-stack">
          <div class="inline-fields compact-fields">
            <label class="field"><span>允许模型</span><input v-model="modelForm.allowed_models" placeholder="GBM, RF, XGBoost" /></label>
            <label class="field"><span>排除模型</span><input v-model="modelForm.excluded_models" placeholder="KNN, SVM" /></label>
          </div>
        </div>

        <div v-else-if="!loading && stage === 'training_validation'" class="form-stack">
          <div class="inline-fields compact-fields">
            <label class="field"><span>训练预算（秒）</span><input v-model.number="trainingForm.time_limit" type="number" min="5" max="300" /></label>
            <label class="field"><span>交叉验证折数</span><input v-model.number="trainingForm.cv_folds" type="number" min="2" max="20" /></label>
            <label class="field"><span>评价指标</span><input v-model="trainingForm.metric_name" placeholder="f1 / rmse" /></label>
          </div>
        </div>

        <div v-else-if="!loading" class="form-stack">
          <label class="field">
            <span>报告重点</span>
            <textarea v-model="reportForm.report_focus" rows="3" placeholder="业务结论, 模型限制, 特征解释" />
          </label>
        </div>

        <div v-if="!loading && riskNotes.length" class="hitl-notes">
          <span v-for="item in riskNotes.slice(0, 2)" :key="item">{{ item }}</span>
        </div>

        <div v-if="!loading && isCodexImprovementReview" class="modal-actions">
          <button class="primary-action" type="button" :disabled="submittingDisabled" @click="submit('continue_improvement')">
            <CheckCircle2 :size="17" />{{ busy ? '正在提交' : '继续改进' }}
          </button>
          <button class="secondary-action" type="button" :disabled="submittingDisabled" @click="submit('stop_and_report')">
            <FileText :size="17" />停止并生成报告
          </button>
          <button class="danger-action" type="button" :disabled="submittingDisabled" @click="submit('reject')">
            <X :size="17" />拒绝任务
          </button>
        </div>

        <div v-else-if="!loading" class="modal-actions">
          <button class="primary-action" type="button" :disabled="submittingDisabled" @click="submit('verify')">
            <CheckCircle2 :size="17" />{{ busy ? '正在提交' : (isCodexPlanApproval ? '确认执行' : '确认继续') }}
          </button>
          <button class="secondary-action" type="button" :disabled="submittingDisabled" @click="submit('retry')">
            <RefreshCw :class="{ spinning: busy }" :size="17" />{{ isCodexPlanApproval ? '重写计划' : '应用调整并重试' }}
          </button>
          <button class="danger-action" type="button" :disabled="submittingDisabled" @click="submit('reject')">
            <X :size="17" />拒绝任务
          </button>
        </div>
      </section>
    </div>
  </Teleport>
</template>
