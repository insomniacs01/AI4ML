export function taskTypeLabel(type) {
  const map = {
    classification: '表格分类',
    regression: '表格回归',
    time_series_forecasting: '时间序列预测',
    image_classification: '图像分类',
  }
  return map[type] || '自动建模'
}

export function taskStatusLabel(status) {
  const map = {
    draft: '草稿',
    uploaded: '已上传',
    planning: '规划中',
    running: '运行中',
    paused_for_review: '已暂停',
    waiting_human: '待人工确认',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    published: '已发布',
  }
  return map[status] || status || '-'
}

export function metricLabel(key) {
  const map = {
    primary_metric: '主指标',
    accuracy: '准确率',
    f1: 'F1',
    precision: '精确率',
    recall: '召回率',
    auc: 'AUC',
    roc_auc: 'AUC',
    r2: 'R2',
    rmse: 'RMSE',
    mae: 'MAE',
    mse: 'MSE',
    ap: '平均精度',
    log_loss: '对数损失',
  }
  return map[key] || String(key || '').replace(/_/g, ' ')
}

export function displayTaskTitle(task, fallback = '任务详情') {
  if (!task) return fallback
  const raw = String(task.display_name || '').trim()
  const target = task.target_column ? `预测${task.target_column}` : '未设置目标'
  const generated = `${taskTypeLabel(task.task_type)}实验：${target}`
  if (!raw) return generated
  if (/^(Classification|Regression|Time Series|Image Classification|AutoML)\s+Task\b/i.test(raw)) return generated
  if (/^(Task|AutoML)\b/i.test(raw)) return generated
  return raw
}

export function teamRoleLabel(role) {
  const map = {
    team_owner: '所有者',
    admin: '管理员',
    member: '成员',
    business_user: '业务用户',
    developer_user: '开发者',
    business: '业务用户',
    developer: '开发者',
    community_admin: '管理员',
  }
  return map[role] || role || '-'
}

export function teamStatusLabel(status) {
  const map = {
    active: '正常',
    frozen: '冻结',
    invited: '已邀请',
    removed: '已移除',
  }
  return map[status] || status || '-'
}
