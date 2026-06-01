<script setup>
import { computed, ref, watch } from 'vue'
import { UploadCloud } from 'lucide-vue-next'

const props = defineProps({
  delivery: { type: Object, default: null },
  disabled: { type: Boolean, default: false },
  submitting: { type: Boolean, default: false },
})
const emit = defineEmits(['submit'])

const rows = ref([{}])
const imageFileName = ref('')

const schema = computed(() => props.delivery?.input_schema || {})
const mode = computed(() => schema.value.input_mode || (schema.value.task_type === 'image_classification' ? 'image' : 'tabular'))
const fields = computed(() => {
  const required = props.delivery?.required_features || schema.value.required_features || schema.value.features || []
  return required.length ? required : ['feature']
})
const dtypes = computed(() => schema.value.dtypes || {})

function emptyRow() {
  const row = {}
  fields.value.forEach((name) => {
    const dtype = String(dtypes.value[name] || '').toLowerCase()
    row[name] = dtype.includes('int') || dtype.includes('float') || dtype.includes('double') || dtype.includes('number') ? 0 : ''
  })
  if (mode.value === 'image') row.image_base64 = ''
  return row
}

function resetRows() {
  if (Array.isArray(props.delivery?.sample_rows) && props.delivery.sample_rows.length) rows.value = props.delivery.sample_rows.map((item) => ({ ...item }))
  else rows.value = [emptyRow()]
}

function addRow() {
  rows.value.push(emptyRow())
}

function removeRow(index) {
  if (rows.value.length > 1) rows.value.splice(index, 1)
}

function fieldType(name) {
  const dtype = String(dtypes.value[name] || '').toLowerCase()
  return dtype.includes('int') || dtype.includes('float') || dtype.includes('double') || dtype.includes('number') ? 'number' : 'text'
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result || ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

async function setImageFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  imageFileName.value = file.name
  rows.value = [{ image_base64: await fileToBase64(file) }]
}

function submitForm() {
  emit('submit', rows.value)
}

watch(() => props.delivery, resetRows, { immediate: true })
</script>

<template>
  <div class="form-stack">
    <template v-if="mode === 'image'">
      <label class="upload-zone compact-upload">
        <UploadCloud :size="24" />
        <strong>{{ imageFileName || '上传图片进行预测' }}</strong>
        <span>支持浏览器可读取的图片文件，系统会自动转为 base64 请求。</span>
        <input type="file" accept="image/*" :disabled="disabled" @change="setImageFile" />
      </label>
    </template>

    <template v-else>
      <div v-for="(row, rowIndex) in rows" :key="rowIndex" class="demo-row-editor">
        <div class="panel-title compact-title">
          <span>样本 {{ rowIndex + 1 }}</span>
          <button class="secondary-action" type="button" :disabled="rows.length <= 1" @click="removeRow(rowIndex)">删除</button>
        </div>
        <div class="inline-fields">
          <label v-for="field in fields" :key="field" class="field">
            <span>{{ field }}</span>
            <input v-model="row[field]" :type="fieldType(field)" :disabled="disabled" />
          </label>
        </div>
      </div>
      <button class="secondary-action" type="button" :disabled="disabled" @click="addRow">添加样本</button>
    </template>

    <button class="primary-action" type="button" :disabled="disabled || submitting || (mode === 'image' && !rows[0]?.image_base64)" @click="submitForm">
      {{ submitting ? '预测中...' : '运行预测' }}
    </button>
  </div>
</template>
