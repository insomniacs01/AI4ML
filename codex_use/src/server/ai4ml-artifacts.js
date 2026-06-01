import { mkdir, readdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import path from 'node:path';

import { ai4mlDataRoot, ai4mlWorkspaceRoot } from './config.js';

const maxDataPathEntries = 800;
const maxDataPathDepth = 6;

export async function listAi4mlDataPaths() {
  const root = path.resolve(ai4mlDataRoot);
  const rootStats = await stat(root);

  if (!rootStats.isDirectory()) {
    throw new Error(`AI4ML data root is not a directory: ${root}`);
  }

  const entries = [];
  await collectDataPathEntries(root, root, entries, 0);

  return {
    root,
    entries: entries.sort((left, right) => {
      if (left.type !== right.type) {
        return left.type === 'directory' ? -1 : 1;
      }
      return left.relativePath.localeCompare(right.relativePath, 'zh-CN');
    })
  };
}

export async function validateAi4mlDataPath(candidatePath) {
  if (typeof candidatePath !== 'string' || !candidatePath.trim()) {
    throw new Error('请选择一个数据文件或文件夹。');
  }

  const resolved = path.resolve(candidatePath);
  const stats = await stat(resolved);

  return {
    path: resolved,
    type: stats.isDirectory() ? 'directory' : 'file',
    size: stats.isFile() ? stats.size : undefined,
    modifiedAt: stats.mtime.toISOString()
  };
}

export async function initializeAi4mlWorkspace(options) {
  const workspaceRoot = path.resolve(ai4mlWorkspaceRoot);
  const workspaceName = buildWorkspaceName(options.taskId);
  const workspacePath = path.join(workspaceRoot, workspaceName);
  const dataPath = path.resolve(options.dataPath);
  const now = new Date().toISOString();

  await mkdir(workspacePath, { recursive: true });
  await rm(path.join(workspacePath, 'output'), { recursive: true, force: true });
  await rm(path.join(workspacePath, 'state'), { recursive: true, force: true });

  await mkdir(path.join(workspacePath, 'input'), { recursive: true });
  await mkdir(path.join(workspacePath, 'work', 'code'), { recursive: true });
  await mkdir(path.join(workspacePath, 'work', 'notebooks'), { recursive: true });
  await mkdir(path.join(workspacePath, 'work', 'scratch'), { recursive: true });
  await mkdir(path.join(workspacePath, 'output', 'code'), { recursive: true });
  await mkdir(path.join(workspacePath, 'output', 'model'), { recursive: true });
  await mkdir(path.join(workspacePath, 'output', 'logs'), { recursive: true });
  await mkdir(path.join(workspacePath, 'state'), { recursive: true });

  await writeJsonFile(path.join(workspacePath, 'input', 'task_request.json'), {
    task_type: 'ai4ml_codex_native_workspace_initialization',
    workspace_status: 'initialized_by_ai4ml_backend',
    description: 'AI4ML 后端已创建 Codex-native 任务工作区；数据路径和用户任务描述是权威任务输入。',
    authoritative_inputs: {
      task_id: options.taskId || null,
      team_id: options.teamId || null,
      data_path: dataPath,
      data_path_type_declared_by_user: options.dataPathType === 'directory' ? '文件夹' : '文件',
      user_task_description: options.description || '',
      approved_plan_id: options.approvedPlanId || null,
      approved_plan_name: options.approvedPlanName || null,
      approved_plan_text: options.approvedPlanText || ''
    },
    input_interpretation_rules: [
      'selected data_path 和 user_task_description 是本任务的权威输入。',
      '必须先判断路径类型和内容结构，再选择读取方式。',
      '如果目标、任务类型、指标或预测范围未完整指定，必须基于数据和任务描述提出可执行默认方案，在 output/plan.md 标为“默认假设”，并等待用户确认。'
    ],
    created_at: now
  });

  await writeTextFile(path.join(workspacePath, 'input', 'project_rules.md'), buildProjectRules());
  await writeTextFile(
    path.join(workspacePath, 'output', 'plan.md'),
    options.approvedPlanText
      ? options.approvedPlanText.trimEnd() + '\n'
      : `# AI4ML 任务计划\n\nCodex 正在读取数据并生成可确认的建模计划。\n`
  );
  await writeJsonFile(path.join(workspacePath, 'output', 'progress.json'), {
    status: 'running',
    current_step: 'dataset_analysis',
    percent: 12,
    summary: 'Codex 运行环境已创建，正在分析数据集并准备生成建模计划。',
    steps: [
      {
        id: 'environment_creation',
        title: '正在创建环境',
        status: 'completed',
        detail: 'AI4ML 后端已创建 Codex-native 任务工作区和协议文件。'
      },
      {
        id: 'dataset_analysis',
        title: '正在分析数据集',
        status: 'running',
        detail: 'Codex 正在读取数据结构、字段和任务描述，准备生成计划。'
      },
      {
        id: 'plan_generation',
        title: '生成工作计划',
        status: 'pending',
        detail: '等待 Codex 写入 output/plan.md。'
      },
      {
        id: 'awaiting_plan_approval',
        title: '等待计划确认',
        status: 'pending',
        detail: '计划生成后将等待用户确认、编辑或要求重写。'
      }
    ],
    updated_at: now
  });
  await writeJsonFile(path.join(workspacePath, 'state', 'artifact_index.json'), {
    workspace: workspaceName,
    status: 'running',
    artifacts: [
      {
        path: 'input/task_request.json',
        type: 'protocol_input',
        description: '记录 AI4ML Codex-native 任务的权威输入。'
      },
      {
        path: 'output/progress.json',
        type: 'progress',
        description: '记录当前任务进度。'
      },
      {
        path: 'output/plan.md',
        type: 'plan',
        description: '计划生成后供用户确认。'
      }
    ],
    updated_at: now
  });

  return {
    name: workspaceName,
    path: workspacePath,
    relativePath: path.relative(process.cwd(), workspacePath),
    createdAt: now
  };
}

export async function getLatestAi4mlWorkspaceArtifacts(options = {}) {
  const sinceMs = Number.isFinite(options.sinceMs) ? options.sinceMs : undefined;
  const workspaceRoot = path.resolve(ai4mlWorkspaceRoot);
  const requestedWorkspacePath = typeof options.workspacePath === 'string' && options.workspacePath.trim()
    ? path.resolve(options.workspacePath)
    : '';

  if (requestedWorkspacePath) {
    try {
      const requestedStats = await stat(requestedWorkspacePath);
      if (!requestedStats.isDirectory()) {
        return {
          workspaceRoot,
          workspace: null
        };
      }
      return readAi4mlWorkspaceArtifacts(workspaceRoot, {
        name: path.basename(requestedWorkspacePath),
        path: requestedWorkspacePath,
        modifiedAtMs: requestedStats.mtimeMs
      });
    } catch {
      return {
        workspaceRoot,
        workspace: null
      };
    }
  }

  let workspaceEntries;

  try {
    workspaceEntries = await readdir(workspaceRoot, { withFileTypes: true });
  } catch {
    return {
      workspaceRoot,
      workspace: null
    };
  }

  const directories = [];
  for (const entry of workspaceEntries) {
    if (!entry.isDirectory()) {
      continue;
    }

    const workspacePath = path.join(workspaceRoot, entry.name);
    try {
      const stats = await stat(workspacePath);
      if (sinceMs !== undefined && stats.mtimeMs < sinceMs) {
        continue;
      }
      directories.push({
        name: entry.name,
        path: workspacePath,
        modifiedAtMs: stats.mtimeMs
      });
    } catch {
      // Ignore directories that disappear while scanning.
    }
  }

  directories.sort((left, right) => right.modifiedAtMs - left.modifiedAtMs);
  const workspace = directories[0];

  if (!workspace) {
    return {
      workspaceRoot,
      workspace: null
    };
  }

  return readAi4mlWorkspaceArtifacts(workspaceRoot, workspace);
}

export async function markLatestAi4mlWorkspaceInterrupted(options = {}) {
  const artifacts = await getLatestAi4mlWorkspaceArtifacts(options);

  if (!artifacts.workspace || !artifacts.progress || artifacts.report?.exists) {
    return artifacts;
  }

  const currentStatus = typeof artifacts.progress.status === 'string'
    ? artifacts.progress.status
    : '';

  if (!['running', 'in_progress', 'executing'].includes(currentStatus)) {
    return artifacts;
  }

  const interruptedAt = options.interruptedAt || new Date().toISOString();
  const reason = options.reason || 'Codex 进程已停止，任务未正常完成。';
  const updatedProgress = {
    ...artifacts.progress,
    status: 'interrupted',
    current_step: 'interrupted',
    summary: reason,
    steps: updateInterruptedSteps(artifacts.progress.steps),
    interrupted_at: interruptedAt,
    updated_at: interruptedAt
  };

  const progressPath = path.join(artifacts.workspace.path, 'output', 'progress.json');
  await writeJsonFile(progressPath, updatedProgress);

  return {
    ...artifacts,
    progress: updatedProgress
  };
}

export async function writeLatestAi4mlTokenUsage(usage, options = {}) {
  const artifacts = await getLatestAi4mlWorkspaceArtifacts(options);
  if (!artifacts.workspace) {
    return null;
  }

  if (isCompletedAi4mlArtifacts(artifacts)) {
    return null;
  }

  const normalizedUsage = normalizeTokenUsage(usage);
  if (!normalizedUsage || normalizedUsage.total.total_tokens <= 0) {
    return null;
  }

  const now = new Date().toISOString();
  const tokenUsagePath = path.join(artifacts.workspace.path, 'output', 'token_usage.json');
  const existing = artifacts.tokenUsage && typeof artifacts.tokenUsage === 'object'
    ? artifacts.tokenUsage
    : {};
  const sessions = existing.sessions && typeof existing.sessions === 'object'
    ? existing.sessions
    : {};
  const sessionName = typeof options.sessionName === 'string' && options.sessionName.trim()
    ? options.sessionName.trim()
    : 'codex';

  const payload = {
    total: normalizedUsage.total,
    sessions: {
      ...sessions,
      [sessionName]: {
        input_tokens: normalizedUsage.total.input_tokens,
        output_tokens: normalizedUsage.total.output_tokens,
        total_tokens: normalizedUsage.total.total_tokens,
        cached_input_tokens: normalizedUsage.total.cached_input_tokens,
        reasoning_output_tokens: normalizedUsage.total.reasoning_output_tokens,
        model_context_window: normalizedUsage.model_context_window
      }
    },
    conversations: {
      codex: {
        input_tokens: normalizedUsage.total.input_tokens,
        output_tokens: normalizedUsage.total.output_tokens,
        total_tokens: normalizedUsage.total.total_tokens
      }
    },
    last: normalizedUsage.last,
    source: 'codex_thread_token_usage_updated',
    calculation_method: 'codex_app_server_token_usage',
    thread_id: normalizedUsage.thread_id,
    turn_id: normalizedUsage.turn_id,
    model_context_window: normalizedUsage.model_context_window,
    updated_at: now
  };

  await writeJsonFile(tokenUsagePath, payload);
  return {
    path: tokenUsagePath,
    usage: payload
  };
}

export function isCompletedAi4mlArtifacts(artifacts) {
  if (!artifacts || typeof artifacts !== 'object') {
    return false;
  }

  const progress = artifacts.progress && typeof artifacts.progress === 'object'
    ? artifacts.progress
    : {};

  return progress.status === 'completed' || Boolean(artifacts.report?.exists && artifacts.predict?.exists);
}

async function collectDataPathEntries(root, currentPath, entries, depth) {
  if (entries.length >= maxDataPathEntries || depth > maxDataPathDepth) {
    return;
  }

  const dirents = await readdir(currentPath, { withFileTypes: true });

  for (const dirent of dirents) {
    if (entries.length >= maxDataPathEntries) {
      return;
    }

    const absolutePath = path.join(currentPath, dirent.name);
    const relativePath = path.relative(root, absolutePath);

    if (!relativePath || relativePath.includes(`${path.sep}.`)) {
      continue;
    }

    let stats;
    try {
      stats = await stat(absolutePath);
    } catch {
      continue;
    }

    if (dirent.isDirectory()) {
      entries.push({
        name: dirent.name,
        path: absolutePath,
        relativePath,
        type: 'directory',
        modifiedAt: stats.mtime.toISOString()
      });
      await collectDataPathEntries(root, absolutePath, entries, depth + 1);
      continue;
    }

    if (dirent.isFile()) {
      entries.push({
        name: dirent.name,
        path: absolutePath,
        relativePath,
        type: 'file',
        size: stats.size,
        modifiedAt: stats.mtime.toISOString()
      });
    }
  }
}

async function readOptionalText(filePath) {
  try {
    return await readFile(filePath, 'utf8');
  } catch {
    return null;
  }
}

async function readOptionalJson(filePath) {
  const text = await readOptionalText(filePath);

  if (!text) {
    return null;
  }

  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function readAi4mlWorkspaceArtifacts(workspaceRoot, workspace) {
  const planPath = path.join(workspace.path, 'output', 'plan.md');
  const progressPath = path.join(workspace.path, 'output', 'progress.json');
  const metricsPath = path.join(workspace.path, 'output', 'metrics.json');
  const tokenUsagePath = path.join(workspace.path, 'output', 'token_usage.json');
  const reportPath = path.join(workspace.path, 'output', 'report.md');
  const predictPath = path.join(workspace.path, 'output', 'predict.py');

  return {
    workspaceRoot,
    workspace: {
      name: workspace.name,
      path: workspace.path,
      modifiedAt: new Date(workspace.modifiedAtMs).toISOString()
    },
    plan: await readOptionalText(planPath),
    progress: await readOptionalJson(progressPath),
    metrics: await readOptionalJson(metricsPath),
    tokenUsage: await readOptionalJson(tokenUsagePath),
    report: {
      path: reportPath,
      exists: Boolean(await readOptionalText(reportPath))
    },
    predict: {
      path: predictPath,
      exists: Boolean(await readOptionalText(predictPath))
    }
  };
}

function updateInterruptedSteps(steps) {
  if (!Array.isArray(steps)) {
    return [
      {
        id: 'interrupted',
        title: '任务已中断',
        status: 'interrupted',
        detail: 'Codex 进程已停止，任务未正常完成。'
      }
    ];
  }

  let hasInterruptedStep = false;
  const updatedSteps = steps.map((step) => {
    if (!step || typeof step !== 'object') {
      return step;
    }

    if (step.status === 'in_progress' || step.status === 'running') {
      hasInterruptedStep = true;
      return {
        ...step,
        status: 'interrupted',
        detail: `${step.detail || ''} 已中断，Codex 进程不再运行。`.trim()
      };
    }

    return step;
  });

  if (!hasInterruptedStep) {
    updatedSteps.push({
      id: 'interrupted',
      title: '任务已中断',
      status: 'interrupted',
      detail: 'Codex 进程已停止，任务未正常完成。'
    });
  }

  return updatedSteps;
}

async function writeJsonFile(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporaryFile = `${filePath}.${process.pid}.tmp`;
  await writeFile(temporaryFile, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await rename(temporaryFile, filePath);
}

async function writeTextFile(filePath, value) {
  await mkdir(path.dirname(filePath), { recursive: true });
  const temporaryFile = `${filePath}.${process.pid}.tmp`;
  await writeFile(temporaryFile, value, 'utf8');
  await rename(temporaryFile, filePath);
}

function normalizeTokenUsage(usage) {
  if (!usage || typeof usage !== 'object') {
    return null;
  }

  const total = normalizeTokenBucket(usage.total || usage);
  const last = normalizeTokenBucket(usage.last || {});
  return {
    total,
    last,
    model_context_window: coerceNonNegativeInt(usage.modelContextWindow || usage.model_context_window),
    thread_id: typeof usage.threadId === 'string' ? usage.threadId : null,
    turn_id: typeof usage.turnId === 'string' ? usage.turnId : null
  };
}

function normalizeTokenBucket(bucket) {
  const value = bucket && typeof bucket === 'object' ? bucket : {};
  const inputTokens = coerceNonNegativeInt(value.inputTokens ?? value.input_tokens ?? value.total_input_tokens);
  const outputTokens = coerceNonNegativeInt(value.outputTokens ?? value.output_tokens ?? value.total_output_tokens);
  const cachedInputTokens = coerceNonNegativeInt(value.cachedInputTokens ?? value.cached_input_tokens);
  const reasoningOutputTokens = coerceNonNegativeInt(value.reasoningOutputTokens ?? value.reasoning_output_tokens);
  const explicitTotal = coerceNonNegativeInt(value.totalTokens ?? value.total_tokens);
  const totalTokens = explicitTotal || inputTokens + outputTokens;
  return {
    total_input_tokens: inputTokens,
    total_output_tokens: outputTokens,
    total_tokens: totalTokens,
    input_tokens: inputTokens,
    output_tokens: outputTokens,
    cached_input_tokens: cachedInputTokens,
    reasoning_output_tokens: reasoningOutputTokens
  };
}

function coerceNonNegativeInt(value) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return Math.max(parsed, 0);
}

function buildWorkspaceName(taskId) {
  const safeTaskId = typeof taskId === 'string'
    ? taskId.trim().replace(/[^A-Za-z0-9._-]/g, '_')
    : '';
  if (safeTaskId) {
    return `ai4ml-${safeTaskId}`;
  }
  const timestamp = new Date().toISOString()
    .replace(/[-:]/g, '')
    .replace(/\..+$/, '')
    .replace('T', '-');
  return `ai4ml-${timestamp}`;
}

function buildProjectRules() {
  return `# AI4ML Codex-native 项目规则

## 执行引擎

- Codex 是唯一执行引擎。
- 用户可见结果必须写入 \`output/\`。
- 不得编造模型指标、排行榜、报告或预测支持。

## 语言规则

- 用户可见沟通和产物默认使用中文。
- 专业名称、模型名称、metric 名称、字段名、文件名、代码标识符、library 名称、命令和原始错误信息可保留原文。
- \`output/plan.md\`、\`output/report.md\`、\`state/questions.json\` 和 \`output/progress.json\` 中的解释性内容默认使用中文。

## 环境与依赖

- 不要在 task workspace、\`work/\`、\`output/\` 或 subagent 目录内创建新的 Python 虚拟环境，例如 \`.venv\`、\`venv\` 或 \`env\`。
- 优先使用项目级 Python 环境或系统已有 Python 解释器执行脚本。
- 如确实需要额外依赖，先记录到 workspace 内的 requirements 文件或报告的复现步骤中，不能在每个 subagent 目录重复安装一套依赖。
- 不要把可重建依赖目录、pip cache、临时安装目录或虚拟环境作为最终产物写入 \`output/\` 或 \`state/artifact_index.json\`。

## 计划与审批

- \`output/plan.md\` 在模型执行前是必需的。
- 收到数据路径后，Codex 必须先检查它是文件还是目录，理解内容和结构，然后生成或更新 \`output/plan.md\`。
- 生成完整默认计划后，Codex 必须将 \`output/progress.json\` 设置为 \`waiting_plan_approval\` 并停止。
- 在用户明确批准计划前，Codex 不得训练模型、运行模型比较、创建 \`output/metrics.json\`、创建 \`output/report.md\` 或创建 \`output/predict.py\`。
- 如果用户修改计划，更新 \`output/plan.md\` 并继续等待批准，除非用户明确要求执行。
- 如果用户要求重新生成计划，重新生成 \`output/plan.md\` 并继续等待批准。
- \`output/progress.json\` 必须反映当前任务状态。

## 数据路径与目标定义

- 选定数据路径可以是任意文件或目录，不得假设一定是 CSV。
- 如果路径是目录，必须梳理其中的文件，识别可能的数据集、元数据、说明文档和已有输出。
- 如果路径是文件，必须基于扩展名、文件签名、内容采样和可用 library 选择读取方式。
- 任务目标可能是单列、多列、多指标、派生目标、非列目标、排序目标、聚类组、缺失值补全、预测区间、报告分析目标或混合流程。
- 计划必须是完整可执行方案，不是问题清单。
- 如果用户没有完整指定目标定义、任务类型、metric、预测范围或业务目标，Codex 必须从数据和任务描述中推断合理默认值，明确标为“默认假设”，并围绕这些默认值制定计划。
`;
}
