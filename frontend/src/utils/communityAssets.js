import { getModelDisplayName } from '@/utils/modelProfile'

export function assetTypeForItem(item) {
  return item?.plan_id ? 'plan' : 'prompt'
}

export function assetIdForItem(item) {
  return item?.plan_id || item?.prompt_id || item?.asset_id || ''
}

export function assetTypeLabel(type) {
  return type === 'plan' ? '执行方案' : '提示词'
}

function excerpt(value, length = 180) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > length ? `${text.slice(0, length)}...` : text
}

export function assetIntro(item, length = 160) {
  if (assetTypeForItem(item) === 'plan') {
    return item.description || excerpt(item.plan_text, length) || `${getModelDisplayName()} 执行方案，可用于跳过重新规划。`
  }
  return item.prompt_description || item.description || '任务主题和描述提示词，可用于快速创建新任务。'
}

export function searchableAssetText(item) {
  return [
    item?.name,
    item?.description,
    item?.prompt_title,
    item?.prompt_description,
    item?.plan_text,
    item?.task_category,
    item?.target_column,
    item?.metric,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}
