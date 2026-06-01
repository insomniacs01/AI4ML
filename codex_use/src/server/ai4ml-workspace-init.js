import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const templatesDir = path.resolve(__dirname, '..', '..', 'templates');
const templatePaths = {
  newTask: path.join(templatesDir, 'ai4ml-new-task-prompt.md'),
  regeneratePlan: path.join(templatesDir, 'ai4ml-regenerate-complete-plan-prompt.md'),
  approvePlan: path.join(templatesDir, 'ai4ml-approve-plan-execute-prompt.md'),
  resumeTask: path.join(templatesDir, 'ai4ml-resume-interrupted-task-prompt.md')
};

const cachedPrompts = new Map();

export async function loadAi4mlWorkspaceInitPrompt() {
  return loadTemplate('newTask');
}

export async function loadAi4mlRegeneratePlanPrompt() {
  return loadTemplate('regeneratePlan');
}

export async function loadAi4mlApprovePlanPrompt() {
  return loadTemplate('approvePlan');
}

export async function loadAi4mlResumeTaskPrompt() {
  return loadTemplate('resumeTask');
}

export async function buildAi4mlStartTaskPrompt({ dataPath, dataPathType, description, workspacePath, workspaceName }) {
  const basePrompt = await loadAi4mlWorkspaceInitPrompt();

  return `${basePrompt.trimEnd()}

---

本次任务输入：

数据路径：

\`\`\`text
${dataPath}
\`\`\`

数据路径类型：${dataPathType === 'directory' ? '文件夹' : '文件'}

用户任务描述：

\`\`\`text
${description || '用户未提供额外任务描述。'}
\`\`\`

请立即开始本次 AI4ML 任务：

- 使用已经创建好的 task workspace，不要另建新目录：

\`\`\`text
${workspacePath || `workspaces/${workspaceName || '{task_id}'}`}
\`\`\`

- 如果该 workspace 中已有 \`input/task_request.json\`、\`input/project_rules.md\`、\`output/progress.json\`、\`output/plan.md\` 和 \`state/artifact_index.json\`，请直接更新它们。
- 将上述数据路径和任务描述写入 \`input/task_request.json\`。
- 数据路径可能是任意文件或文件夹，不要假设一定是 CSV。请先判断路径类型和内容结构，再选择合适的读取方式。
- 如果是文件夹，请梳理文件结构，识别可用的数据文件、说明文档、元数据和结果文件，再决定任务输入。
- 如果是文件，请根据扩展名、文件头、内容采样和可用库选择读取方式。
- 预测或分析目标可能是单目标、多目标、多指标、非列名目标、排序、聚类、缺失补全、时间序列、报告分析或混合任务。必须根据用户描述和数据结构形成明确的目标定义，不要默认只有一个 target column。
- 如果用户描述没有完整指定目标、任务类型、指标或预测范围，请基于数据自行给出可执行默认方案，在 \`output/plan.md\` 标为“默认假设”，并停止等待用户确认。
- 只生成和更新计划，不要在计划确认前训练模型或生成最终报告。
`;
}

export async function buildAi4mlStartTaskWithApprovedPlanPrompt({ dataPath, dataPathType, description, workspacePath, workspaceName, approvedPlanText, approvedPlanName }) {
  const approvePrompt = await buildAi4mlApprovePlanPrompt(approvedPlanText);

  return `#AI4ML_START_TASK_WITH_COMMUNITY_PLAN

用户创建任务时已经选择并确认了一个可复用执行方案。请跳过重新规划，直接按该方案执行完整 AI4ML 建模流程。

任务输入：

数据路径：

\`\`\`text
${dataPath}
\`\`\`

数据路径类型：${dataPathType === 'directory' ? '文件夹' : '文件'}

用户任务描述：

\`\`\`text
${description || '用户未提供额外任务描述。'}
\`\`\`

已选择方案：${approvedPlanName || '社区方案'}

必须使用已经创建好的 task workspace，不要另建新目录：

\`\`\`text
${workspacePath || `workspaces/${workspaceName || '{task_id}'}`}
\`\`\`

${approvePrompt}`;
}

export async function buildAi4mlApprovePlanPrompt(planText) {
  const approvePrompt = await loadAi4mlApprovePlanPrompt();

  return `#AI4ML_APPROVE_PLAN_WITH_EDITED_PLAN

用户已经在前端确认或编辑了计划。请先用下面的内容覆盖当前 task workspace 的 \`output/plan.md\`，然后严格按该计划执行完整流程。

确认后的计划内容：

\`\`\`markdown
${planText || ''}
\`\`\`

${approvePrompt.trimStart()}`;
}

export async function buildAi4mlResumeTaskPrompt(workspacePath) {
  const resumePrompt = await loadAi4mlResumeTaskPrompt();

  return resumePrompt.replaceAll('{workspace_path}', workspacePath);
}

async function loadTemplate(name) {
  if (cachedPrompts.has(name)) {
    return cachedPrompts.get(name);
  }

  const templatePath = templatePaths[name];
  const prompt = await readFile(templatePath, 'utf8');
  cachedPrompts.set(name, prompt);
  return prompt;
}
