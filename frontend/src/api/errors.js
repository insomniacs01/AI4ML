export function errorDetailToText(detail) {
  if (detail === null || detail === undefined) return ''
  if (typeof detail === 'string') return detail.trim()
  if (Array.isArray(detail)) {
    return detail
      .map((item) => errorDetailToText(item))
      .filter(Boolean)
      .join('；')
      .slice(0, 1200)
  }
  if (typeof detail === 'object') {
    const loc = Array.isArray(detail.loc) ? detail.loc.filter((item) => item !== 'body').join('.') : ''
    const message = detail.msg || detail.message || detail.error_description || detail.error
    if (message) return `${loc ? `${loc}: ` : ''}${String(message).trim()}`
    if (detail.detail) return errorDetailToText(detail.detail)
    try {
      return JSON.stringify(detail)
    } catch {
      return String(detail)
    }
  }
  return String(detail).trim()
}

export function localizeError(detail, status) {
  const text = errorDetailToText(detail)
  const normalized = text.toLowerCase()
  if (normalized.includes('invalid login credentials')) return 'Invalid email or password.'
  if (normalized.includes('user already registered')) return 'This email is already registered.'
  if (normalized.includes('missing supabase bearer token')) return 'Login expired. Please sign in again.'
  if (normalized.includes('supabase rejected the provided access token')) return 'Login expired. Please sign in again.'
  if (normalized.includes('x-team-id header is required')) return 'Please select a team first.'
  if (normalized.includes('you do not have access to the requested team')) return 'You do not have access to this team.'
  if (normalized.includes('membership in the requested team is not active')) return 'Your team membership is not active.'
  if (normalized.includes('dataset has not been uploaded')) return 'Please upload a CSV dataset first.'
  if (normalized.includes('only csv uploads are supported')) return 'Only CSV uploads are supported.'
  if (normalized.includes('task not found')) return 'Task not found.'
  if (normalized.includes('requires a developer or team admin role')) return 'Developer or team admin role is required.'
  if (normalized.includes('requires a team admin role')) return 'Team admin role is required.'
  if (normalized.includes('open human collaboration requests')) return 'There are open human confirmation requests.'
  if (normalized.includes('waiting for human collaboration')) return 'The task is waiting for human confirmation.'
  if (normalized.includes('已有 codex 任务正在进行') || normalized.includes('一次只能运行一个任务')) {
    return text
  }
  if (normalized.includes('could not reach supabase')) return 'Could not reach the task database.'
  if (normalized.includes('supabase task request failed')) return 'Task database request failed.'
  if (!text && status === 404) return 'Resource not found.'
  if (!text && status === 401) return 'Please sign in first.'
  if (!text && status === 502) return 'Could not reach the task database.'
  return text || `请求失败：HTTP ${status}`
}
