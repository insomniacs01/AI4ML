import { request } from '@/api/request'

const NO_EDITABLE_CODE_MESSAGE = '当前任务还没有可编辑源码。'
const codePathByTask = new Map()

async function chooseCodeArtifact(taskId) {
  const workspace = await request(`/tasks/${taskId}/code-workspace`)
  const items = workspace.items || []
  const item = items.find((entry) => entry.path === 'output/code/final_modeling.py')
    || items.find((entry) => entry.artifact_kind === 'final_modeling')
    || items.find((entry) => entry.path === 'output/predict.py')
    || items.find((entry) => entry.artifact_kind === 'predict_entrypoint')
    || items.find((entry) => entry.is_core && entry.editable)
    || items.find((entry) => entry.editable)
    || items.find((entry) => entry.category === 'code')
  if (!item) {
    codePathByTask.set(taskId, '')
    return { workspace, item: null }
  }
  codePathByTask.set(taskId, item.editable ? item.path : '')
  return { workspace, item }
}

export async function getOperationCode(taskId) {
  const { item } = await chooseCodeArtifact(taskId)
  if (!item) return { content: '', editable: false, detail: NO_EDITABLE_CODE_MESSAGE }
  const content = await request(`/tasks/${taskId}/code-workspace/file?${new URLSearchParams({ path: item.path })}`)
  return {
    ...content,
    editable: Boolean(item.editable),
    detail: item.editable ? '' : '当前源码产物只读，不能在页面内保存或验证。',
  }
}

export async function updateOperationCode(taskId, content) {
  if (!codePathByTask.has(taskId)) await chooseCodeArtifact(taskId)
  const path = codePathByTask.get(taskId)
  if (!path) throw new Error(NO_EDITABLE_CODE_MESSAGE)
  return request(`/tasks/${taskId}/code-workspace/file`, {
    method: 'PUT',
    body: JSON.stringify({ path, content }),
  })
}

export async function validateOperationCode(taskId, payload = {}) {
  if (!codePathByTask.has(taskId)) await chooseCodeArtifact(taskId)
  const path = codePathByTask.get(taskId)
  if (!path) return { valid: false, detail: NO_EDITABLE_CODE_MESSAGE }
  const result = await request(`/tasks/${taskId}/code-workspace/rerun`, {
    method: 'POST',
    body: JSON.stringify({ path, time_limit_seconds: payload.time_limit_seconds || 300 }),
  })
  return { valid: Boolean(result.success), ...result }
}
