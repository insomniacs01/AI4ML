import { detailFromTask } from '@/api/mappers'
import { request } from '@/api/request'

export async function getDelivery(taskId) {
  const task = await request(`/tasks/${taskId}?sync=false`)
  const detail = detailFromTask(task)
  const profile = detail.task.dataset_profile || {}
  const targets = new Set(detail.task.target_columns || (detail.task.target_column ? [detail.task.target_column] : []))
  const columns = (profile.columns || []).map((item) => item.name).filter((name) => name && !targets.has(name))
  const dtypes = Object.fromEntries((profile.columns || []).map((item) => [item.name, item.inferred_type]))
  const sample = profile.preview_rows?.[0] || {}
  return {
    task_id: taskId,
    required_features: columns,
    input_schema: { features: columns, required_features: columns, dtypes, task_type: detail.task.task_type },
    sample_rows: columns.length ? [Object.fromEntries(columns.map((name) => [name, sample[name] ?? '']))] : [{}],
  }
}

export async function getPublicDemo(deploymentId) {
  throw new Error(`公开模型演示 ${deploymentId} 尚未接入后端部署读取接口。`)
}

export async function predictPublicDemo(deploymentId, rows) {
  void rows
  throw new Error(`公开模型演示 ${deploymentId} 尚未接入后端预测接口。`)
}

export async function predict(taskId, rows) {
  const first = Array.isArray(rows) ? rows[0] : rows
  return request(`/tasks/${taskId}/prediction-demo`, {
    method: 'POST',
    body: JSON.stringify({ features: first || {} }),
  })
}
