import { request } from '@/api/request'

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
  if (!item) return { workspace, item: null }
  codePathByTask.set(taskId, item.path)
  return { workspace, item }
}

export async function getOperationCode(taskId) {
  const { item } = await chooseCodeArtifact(taskId)
  if (!item) return { content: '' }
  return request(`/tasks/${taskId}/code-workspace/file?${new URLSearchParams({ path: item.path })}`)
}

export async function updateOperationCode(taskId, content) {
  const path = codePathByTask.get(taskId) || (await chooseCodeArtifact(taskId)).item?.path
  if (!path) throw new Error('No editable code artifact was found.')
  return request(`/tasks/${taskId}/code-workspace/file`, {
    method: 'PUT',
    body: JSON.stringify({ path, content }),
  })
}

export async function validateOperationCode(taskId, payload = {}) {
  const path = codePathByTask.get(taskId) || (await chooseCodeArtifact(taskId)).item?.path
  if (!path) return { valid: false, detail: 'No code artifact is available for validation.' }
  const result = await request(`/tasks/${taskId}/code-workspace/rerun`, {
    method: 'POST',
    body: JSON.stringify({ path, time_limit_seconds: payload.time_limit_seconds || 300 }),
  })
  return { valid: Boolean(result.success), ...result }
}
