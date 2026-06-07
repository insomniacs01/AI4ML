export function buildTaskStatePollTransition(artifacts, reportedTaskStates, options = {}) {
  const now = typeof options.now === 'function' ? options.now : Date.now;
  const reportedStates = reportedTaskStates instanceof Set ? reportedTaskStates : new Set();
  const newlyReportedStates = [];
  const events = [];
  const workspace = artifacts?.workspace;
  const progress = artifacts?.progress && typeof artifacts.progress === 'object'
    ? artifacts.progress
    : null;
  const hasPlan = typeof artifacts?.plan === 'string' && artifacts.plan.trim().length > 0;
  const reportExists = Boolean(artifacts?.report?.exists);

  const hasReported = (state) => reportedStates.has(state) || newlyReportedStates.includes(state);
  const markReported = (state) => {
    if (!hasReported(state)) {
      newlyReportedStates.push(state);
    }
  };

  const transition = {
    events,
    reportedStates: newlyReportedStates,
    activeWorkspacePath: undefined,
    taskCompleted: false,
    stopPolling: false,
    stopCompletedTaskTurn: false
  };

  if (workspace && !hasReported('workspace_ready')) {
    markReported('workspace_ready');
    transition.activeWorkspacePath = workspace.path;
    events.push({
      type: 'workspace_ready',
      workspacePath: workspace.path,
      timestamp: now()
    });
    events.push({
      type: 'requirements_analysis_started',
      timestamp: now()
    });
  }

  if (reportExists || progress?.status === 'completed') {
    transition.taskCompleted = true;
    transition.stopPolling = true;
    transition.stopCompletedTaskTurn = true;
    events.push({
      type: 'task_completed',
      workspacePath: workspace?.path,
      reportPath: artifacts?.report?.path,
      timestamp: now()
    });
    events.push({
      type: 'activity',
      label: 'Ready',
      status: 'online'
    });
    return transition;
  }

  if (workspace && hasPlan && !hasReported('plan_written')) {
    markReported('plan_written');
    events.push({
      type: 'requirements_analysis_completed',
      timestamp: now()
    });
    events.push({
      type: 'plan_generation_started',
      timestamp: now()
    });
  }

  if (progress?.status === 'waiting_plan_approval' && !hasReported('plan_approval_ready')) {
    markReported('plan_approval_ready');
    transition.stopPolling = true;
    events.push({
      type: 'plan_generation_completed',
      workspacePath: workspace?.path,
      timestamp: now()
    });
  }

  return transition;
}

export function buildProgressRecordsForTaskStateTransition(transition, artifacts) {
  const workspacePath = artifacts?.workspace?.path;
  if (!workspacePath || !transition || typeof transition !== 'object') {
    return [];
  }

  const records = [];
  if (Array.isArray(transition.reportedStates) && transition.reportedStates.includes('plan_approval_ready')) {
    records.push({
      workspacePath,
      payload: {
        event: 'plan_generated',
        actor: 'codex_use',
        message: 'Codex 已写入执行计划，等待用户确认。',
        evidence: ['output/plan.md']
      }
    });
  }
  if (transition.taskCompleted) {
    records.push({
      workspacePath,
      payload: {
        event: 'completed',
        actor: 'codex_use',
        message: 'Codex 建模任务已完成，最终产物已可读取。',
        evidence: completionEvidenceForArtifacts(artifacts)
      }
    });
  }
  return records;
}

function completionEvidenceForArtifacts(artifacts) {
  const evidence = ['output/progress.json'];
  if (artifacts?.metrics && typeof artifacts.metrics === 'object') {
    evidence.push('output/metrics.json');
  }
  if (artifacts?.report?.exists) {
    evidence.push('output/report.md');
  }
  if (artifacts?.predict?.exists) {
    evidence.push('output/predict.py');
  }
  return evidence;
}
