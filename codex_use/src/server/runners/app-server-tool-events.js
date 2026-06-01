
import process from 'node:process';

import { createSessionId, extractText } from '../utils.js';

export const toolEventHandlers = {
  handleCommandStarted(item) {
    const toolUseId = typeof item.id === 'string' ? item.id : createSessionId();
    const command = this.commandToString(item.command);
    const cwd = typeof item.cwd === 'string' ? item.cwd : process.cwd();

    this.toolCallsByItemId.set(toolUseId, {
      type: 'command',
      command,
      cwd,
      stdout: '',
      stderr: '',
      startedAt: Date.now()
    });

    this.send({
      type: 'tool_start',
      toolUseId,
      tool: 'command',
      title: 'Running command',
      command,
      cwd,
      startedAt: Date.now()
    });
  },

  handleCommandOutputDelta(params) {
    const toolUseId = typeof params.itemId === 'string' ? params.itemId : undefined;

    if (!toolUseId) {
      return;
    }

    const output = this.extractOutputDelta(params);

    if (!output.data.trim()) {
      this.handleToolProgress(toolUseId);
      return;
    }

    const tool = this.ensureToolRecord(toolUseId, 'command');
    if (output.stream === 'stderr') {
      tool.stderr += output.data;
    } else {
      tool.stdout += output.data;
    }

    this.send({
      type: 'tool_output',
      toolUseId,
      stream: output.stream,
      data: output.data
    });
  },

  handleCommandCompleted(item) {
    const toolUseId = typeof item.id === 'string' ? item.id : createSessionId();
    const command = this.commandToString(item.command);
    const tool = this.ensureToolRecord(toolUseId, 'command');

    if (!tool.startedAt) {
      this.handleCommandStarted(item);
    }

    if (typeof item.stdout === 'string' && item.stdout.trim()) {
      tool.stdout = item.stdout;
    }

    if (typeof item.stderr === 'string' && item.stderr.trim()) {
      tool.stderr = item.stderr;
    }

    const exitCode = typeof item.exitCode === 'number' ? item.exitCode : 0;
    const durationMs = typeof item.durationMs === 'number' ? item.durationMs : Date.now() - (tool.startedAt || Date.now());

    this.send({
      type: 'tool_result',
      toolUseId,
      tool: 'command',
      title: exitCode === 0 ? 'Ran command' : 'Command failed',
      command: command || tool.command || '',
      cwd: typeof item.cwd === 'string' ? item.cwd : tool.cwd || process.cwd(),
      stdout: tool.stdout || '',
      stderr: tool.stderr || '',
      exitCode,
      status: item.status || (exitCode === 0 ? 'completed' : 'failed'),
      durationMs,
      completedAt: Date.now()
    });
  },

  handleFileChangeStarted(item) {
    const toolUseId = typeof item.id === 'string' ? item.id : createSessionId();
    const changes = Array.isArray(item.changes) ? item.changes : [];
    const title = changes.length === 1 ? 'Changing file' : `Changing ${changes.length || 1} files`;

    this.toolCallsByItemId.set(toolUseId, {
      type: 'file_change',
      changes,
      startedAt: Date.now()
    });

    this.send({
      type: 'tool_start',
      toolUseId,
      tool: 'file_change',
      title,
      changes,
      startedAt: Date.now()
    });
  },

  handleFileChangeCompleted(item) {
    const toolUseId = typeof item.id === 'string' ? item.id : createSessionId();
    const changes = Array.isArray(item.changes) ? item.changes : [];
    const tool = this.ensureToolRecord(toolUseId, 'file_change');
    const summary = changes
      .map((change) => `${this.safeKind(change.kind)}: ${change.path || ''}`.trim())
      .filter(Boolean)
      .join('\n');

    if (!tool.startedAt) {
      this.handleFileChangeStarted(item);
    }

    this.send({
      type: 'tool_result',
      toolUseId,
      tool: 'file_change',
      title: item.status === 'failed' ? 'File change failed' : 'Changed files',
      changes,
      output: summary,
      status: item.status || 'completed',
      durationMs: Date.now() - (tool.startedAt || Date.now()),
      completedAt: Date.now()
    });
  },

  handleSimpleToolStarted(item, toolType, title, input) {
    const toolUseId = typeof item.id === 'string' ? item.id : createSessionId();
    this.toolCallsByItemId.set(toolUseId, {
      type: toolType,
      input,
      startedAt: Date.now()
    });
    this.send({
      type: 'tool_start',
      toolUseId,
      tool: toolType,
      title,
      input,
      startedAt: Date.now()
    });
  },

  handleSimpleToolCompleted(item, failed) {
    const toolUseId = typeof item.id === 'string' ? item.id : createSessionId();
    const tool = this.ensureToolRecord(toolUseId, item.type || 'tool');
    this.send({
      type: 'tool_result',
      toolUseId,
      tool: tool.type,
      title: failed ? 'Tool failed' : 'Tool completed',
      output: this.extractToolSummary(item),
      status: item.status || (failed ? 'failed' : 'completed'),
      durationMs: Date.now() - (tool.startedAt || Date.now()),
      completedAt: Date.now()
    });
  },

  handleCollabAgentStarted(item) {
    const toolUseId = typeof item.id === 'string' ? item.id : createSessionId();
    const collabAgent = this.normalizeCollabAgentToolCall(item);
    const title = this.collabAgentTitle(collabAgent.tool, collabAgent.status, collabAgent);

    this.toolCallsByItemId.set(toolUseId, {
      type: 'collab_agent',
      collabAgent,
      startedAt: Date.now()
    });

    this.send({
      type: 'tool_start',
      toolUseId,
      tool: 'collab_agent',
      title,
      input: collabAgent,
      collabAgent,
      startedAt: Date.now()
    });
  },

  handleCollabAgentCompleted(item) {
    const toolUseId = typeof item.id === 'string' ? item.id : createSessionId();
    const collabAgent = this.normalizeCollabAgentToolCall(item);
    const failed = collabAgent.status === 'failed';
    const tool = this.ensureToolRecord(toolUseId, 'collab_agent');

    if (!tool.startedAt) {
      this.handleCollabAgentStarted(item);
    }

    tool.collabAgent = collabAgent;

    this.send({
      type: 'tool_result',
      toolUseId,
      tool: 'collab_agent',
      title: this.collabAgentTitle(collabAgent.tool, collabAgent.status, collabAgent),
      output: this.collabAgentSummary(collabAgent),
      status: failed ? 'failed' : 'completed',
      durationMs: Date.now() - (tool.startedAt || Date.now()),
      collabAgent,
      completedAt: Date.now()
    });
  },

  handleToolProgress(toolUseId) {
    if (typeof toolUseId !== 'string') {
      return;
    }

    this.send({
      type: 'tool_progress',
      toolUseId,
      elapsedMs: Date.now() - (this.toolCallsByItemId.get(toolUseId)?.startedAt || Date.now())
    });
  },

  ensureToolRecord(toolUseId, type) {
    if (!this.toolCallsByItemId.has(toolUseId)) {
      this.toolCallsByItemId.set(toolUseId, {
        type,
        stdout: '',
        stderr: '',
        startedAt: Date.now()
      });
    }

    return this.toolCallsByItemId.get(toolUseId);
  },

  commandToString(command) {
    if (Array.isArray(command)) {
      return command.join(' ');
    }

    if (typeof command === 'string') {
      return command;
    }

    return '';
  },

  extractOutputDelta(params) {
    const stream = params.stream === 'stderr' || params.fd === 2 ? 'stderr' : 'stdout';
    const candidates = [params.delta, params.data, params.chunk, params.output, params.stdout, params.stderr];
    const data = candidates
      .map((value) => (typeof value === 'string' ? value : extractText(value)))
      .find((value) => value);

    return {
      stream: params.stderr ? 'stderr' : stream,
      data: data || ''
    };
  },

  safeKind(kind) {
    if (typeof kind === 'string') {
      return kind;
    }

    if (kind && typeof kind === 'object' && typeof kind.type === 'string') {
      return kind.type;
    }

    return 'modify';
  },

  normalizeCollabAgentToolCall(item) {
    const agentsStates = item.agentsStates && typeof item.agentsStates === 'object'
      ? Object.fromEntries(Object.entries(item.agentsStates).map(([agentId, state]) => [
        agentId,
        {
          status: typeof state?.status === 'string' ? state.status : '',
          message: typeof state?.message === 'string' ? state.message : ''
        }
      ]))
      : {};

    return {
      tool: typeof item.tool === 'string' ? item.tool : 'agent',
      status: typeof item.status === 'string' ? item.status : 'inProgress',
      senderThreadId: typeof item.senderThreadId === 'string' ? item.senderThreadId : '',
      receiverThreadIds: Array.isArray(item.receiverThreadIds)
        ? item.receiverThreadIds.filter((threadId) => typeof threadId === 'string')
        : [],
      prompt: typeof item.prompt === 'string' ? item.prompt : '',
      model: typeof item.model === 'string' ? item.model : '',
      reasoningEffort: typeof item.reasoningEffort === 'string' ? item.reasoningEffort : '',
      agentsStates
    };
  },

  collabAgentTitle(tool, status, collabAgent) {
    const actionLabels = {
      spawnAgent: 'Spawn subagent',
      sendInput: 'Send input',
      resumeAgent: 'Resume subagent',
      wait: 'Wait for subagents',
      closeAgent: 'Close subagent'
    };
    const baseTitle = actionLabels[tool] || 'Subagent action';
    const count = this.collabAgentCountLabel(collabAgent);
    const promptSummary = tool === 'spawnAgent' ? this.collabAgentPromptSummary(collabAgent) : '';
    const titleParts = [baseTitle, count, promptSummary].filter(Boolean);
    const title = titleParts.join(' · ');

    if (status === 'failed') {
      return `${title} failed`;
    }

    if (status === 'completed') {
      return `${title} completed`;
    }

    return title;
  },

  collabAgentCountLabel(collabAgent) {
    const count = Array.isArray(collabAgent?.receiverThreadIds) ? collabAgent.receiverThreadIds.length : 0;
    if (count === 0) {
      return '';
    }
    if (count === 1) {
      return '1 agent';
    }
    return `${count} agents`;
  },

  collabAgentPromptSummary(collabAgent) {
    const prompt = typeof collabAgent?.prompt === 'string' ? collabAgent.prompt.trim() : '';
    if (!prompt) {
      return '';
    }

    const normalized = prompt.replace(/\s+/g, ' ');
    return normalized.length > 42 ? `${normalized.slice(0, 42)}...` : normalized;
  },

  collabAgentSummary(collabAgent) {
    const parts = [
      `tool: ${collabAgent.tool}`,
      `status: ${collabAgent.status}`
    ];

    if (collabAgent.receiverThreadIds.length > 0) {
      parts.push(`threads: ${collabAgent.receiverThreadIds.join(', ')}`);
    }

    const stateLines = Object.entries(collabAgent.agentsStates)
      .map(([agentId, state]) => {
        const message = state.message ? ` - ${state.message}` : '';
        return `${agentId}: ${state.status || 'unknown'}${message}`;
      });

    if (stateLines.length > 0) {
      parts.push(`agents:\n${stateLines.join('\n')}`);
    }

    return parts.join('\n');
  },

  extractToolSummary(item) {
    return [item.result, item.error, item.output, item.summary]
      .map((value) => (typeof value === 'string' ? value : extractText(value)))
      .find((value) => value) || '';
  }
};
