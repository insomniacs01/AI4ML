export function taskProgressPercent({ status, progressPercent = null } = {}) {
  if (status === 'completed') return 100
  if (['draft', 'uploaded', 'planning'].includes(status)) return 0
  if (['failed', 'cancelled'].includes(status)) {
    return nonCompletionTerminalPercent(progressPercent)
  }

  if (progressPercent === null || progressPercent === undefined || progressPercent === '') return null
  const backendPercent = Number(progressPercent)
  if (Number.isFinite(backendPercent)) {
    return Math.min(99, Math.max(0, Math.round(backendPercent)))
  }
  return null
}

export function progressUnavailableText(reason) {
  const map = {
    workspace_not_ready: '任务已提交，工作区尚未返回真实进度。',
    progress_file_missing: '运行工作区缺少 output/progress.json，需要检查 Codex 进度写入。',
    progress_file_unreadable: 'output/progress.json 无法解析，需要修复进度文件。',
    progress_percent_missing: '进度文件未写入真实 percent/progress_percent。',
    progress_percent_invalid: '进度文件中的 percent/progress_percent 不是有效数字。',
    progress_not_available: '当前没有可用的真实进度。',
  }
  return map[reason] || '当前没有可用的真实进度。'
}

function nonCompletionTerminalPercent(progressPercent) {
  if (progressPercent === null || progressPercent === undefined || progressPercent === '') return null
  const backendPercent = Number(progressPercent)
  if (Number.isFinite(backendPercent) && backendPercent < 100) {
    return Math.max(0, Math.round(backendPercent))
  }
  return null
}
