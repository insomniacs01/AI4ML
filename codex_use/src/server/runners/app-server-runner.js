import { spawn } from 'node:child_process';
import process from 'node:process';

import { defaultCodexModel } from '../config.js';
import { clearSavedThread, getSavedThread, saveThread } from '../session-store.js';
import { getCodexCommand, killProcessTree } from '../utils.js';
import { AppServerRpcClient } from './app-server-rpc-client.js';
import { messageEventHandlers } from './app-server-message-events.js';
import { normalizeTokenUsageUpdate } from './app-server-token-usage.js';
import { toolEventHandlers } from './app-server-tool-events.js';

export class AppServerRunner extends AppServerRpcClient {
  constructor(send) {
    super();
    this.send = typeof send === 'function' ? send : () => {};
    this.currentProcess = undefined;
    this.threadId = undefined;
    this.currentTurnId = undefined;
    this.startingTurn = false;
    this.initialized = false;
    this.initializing = false;
    this.nextRequestId = 1;
    this.pendingRequests = new Map();
    this.pendingPrompts = [];
    this.queuedPrompts = [];
    this.initializationPromise = undefined;
    this.stdoutBuffer = '';
    this.stderrBuffer = '';
    this.agentTextByItemId = new Map();
    this.reasoningTextByItemId = new Map();
    this.toolCallsByItemId = new Map();
    this.currentTurnStartedAt = undefined;
    this.forceFreshThread = false;
    this.requestedThreadId = undefined;
  }

  get commandLabel() {
    return 'codex app-server --listen stdio://';
  }

  start(options = {}) {
    const requestedThreadId = typeof options.threadId === 'string' && options.threadId.trim()
      ? options.threadId.trim()
      : undefined;
    this.stop();
    this.threadId = undefined;
    this.currentTurnId = undefined;
    this.startingTurn = false;
    this.initialized = false;
    this.initializing = false;
    this.nextRequestId = 1;
    this.pendingRequests.clear();
    this.pendingPrompts = [];
    this.rejectQueuedPrompts(new Error('Codex app-server restarted.'));
    this.initializationPromise = undefined;
    this.stdoutBuffer = '';
    this.stderrBuffer = '';
    this.agentTextByItemId.clear();
    this.reasoningTextByItemId.clear();
    this.toolCallsByItemId.clear();
    this.currentTurnStartedAt = undefined;
    this.requestedThreadId = requestedThreadId;

    const codexCommand = getCodexCommand();
    const args = [...codexCommand.prefixArgs, 'app-server', '--listen', 'stdio://'];

    try {
      this.currentProcess = spawn(codexCommand.command, args, {
        cwd: process.cwd(),
        env: {
          ...process.env,
          NO_UPDATE_NOTIFIER: '1'
        },
        shell: false,
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true
      });
    } catch (error) {
      this.send({
        type: 'error',
        message: error.message
      });
      return;
    }

    const spawnedProcess = this.currentProcess;

    spawnedProcess.stdout.on('data', (chunk) => this.handleStdout(chunk));
    spawnedProcess.stderr.on('data', (chunk) => this.handleStderr(chunk));
    spawnedProcess.on('error', (error) => {
      this.send({
        type: 'error',
        message: error.message
      });
      this.rejectPendingRequests(error);
      this.rejectQueuedPrompts(error);
      this.currentProcess = undefined;
      this.currentTurnId = undefined;
      this.startingTurn = false;
      this.currentTurnStartedAt = undefined;
    });

    spawnedProcess.on('close', (exitCode, signal) => {
      if (this.currentProcess !== spawnedProcess) {
        return;
      }

      if (this.stdoutBuffer.trim()) {
        this.handleJsonLine(this.stdoutBuffer);
      }

      if (this.stderrBuffer.trim()) {
        this.send({
          type: 'raw',
          stream: 'stderr',
          data: this.stderrBuffer
        });
      }

      this.rejectPendingRequests(new Error('Codex app-server closed.'));
      this.rejectQueuedPrompts(new Error('Codex app-server closed.'));
      this.currentProcess = undefined;
      this.currentTurnId = undefined;
      this.startingTurn = false;
      this.currentTurnStartedAt = undefined;
      this.initialized = false;
      this.initializing = false;
      this.send({
        type: 'exit',
        exitCode,
        signal
      });
    });

    this.send({
      type: 'activity',
      label: 'Starting',
      status: 'pending'
    });

    this.initializationPromise = this.initializeSession();
  }

  stop() {
    if (this.currentProcess) {
      killProcessTree(this.currentProcess);
      this.currentProcess = undefined;
    }

    this.currentTurnId = undefined;
    this.startingTurn = false;
    this.currentTurnStartedAt = undefined;
    this.rejectPendingRequests(new Error('Codex app-server stopped.'));
    this.rejectQueuedPrompts(new Error('Codex app-server stopped.'));
    this.initialized = false;
    this.initializing = false;
    this.initializationPromise = undefined;
  }

  restart() {
    this.forceFreshThread = true;
    this.start();
  }

  resumeThread(threadId) {
    this.forceFreshThread = false;
    this.start({ threadId });
  }

  reloadConfig() {
    this.forceFreshThread = false;
    this.start();
  }

  async sendPrompt(promptText, options = {}) {
    if (!this.currentProcess) {
      this.start();
    }

    if (!this.initialized) {
      this.send({
        type: 'activity',
        label: 'Starting',
        status: 'pending'
      });
      await this.initializationPromise;
    }

    if (this.currentTurnId || this.startingTurn) {
      if (options.queueIfBusy) {
        this.queuePrompt(promptText);
        this.send({
          type: 'activity',
          label: 'Queued',
          status: 'pending'
        });
        return {
          threadId: this.threadId,
          turnId: this.currentTurnId,
          queued: true
        };
      }
      this.send({
        type: 'error',
        message: 'Codex is already running.'
      });
      return { threadId: this.threadId, turnId: this.currentTurnId, busy: true };
    }

    return this.startTurn(promptText);
  }

  queuePrompt(promptText) {
    if (typeof promptText !== 'string' || !promptText.trim()) {
      return;
    }
    this.queuedPrompts.push(promptText);
  }

  hasQueuedPrompts() {
    return this.queuedPrompts.length > 0 || this.pendingPrompts.length > 0;
  }

  hasActiveOrQueuedTurn() {
    return Boolean(this.currentTurnId || this.startingTurn || this.hasQueuedPrompts());
  }

  async startNextQueuedPrompt() {
    if (this.currentTurnId || !this.currentProcess || !this.initialized) {
      return;
    }
    const promptText = this.queuedPrompts.shift();
    if (!promptText) {
      return;
    }
    await this.startTurn(promptText);
  }

  rejectQueuedPrompts(error) {
    if (this.queuedPrompts.length) {
      this.queuedPrompts = [];
      this.send({
        type: 'error',
        message: error.message
      });
    }
  }

  async interrupt() {
    if (!this.currentTurnId) {
      this.send({
        type: 'activity',
        label: 'Ready',
        status: 'online'
      });
      return;
    }

    try {
      await this.call('turn/interrupt', {
        threadId: this.threadId,
        turnId: this.currentTurnId
      }, 15000);
    } catch (error) {
      this.send({
        type: 'error',
        message: `Failed to interrupt Codex: ${error.message}`
      });
    }

    this.currentTurnId = undefined;
    this.startingTurn = false;
    this.send({
      type: 'activity',
      label: 'Interrupted',
      status: 'pending'
    });
  }

  async initializeSession() {
    if (this.initializing || this.initialized) {
      return;
    }

    this.initializing = true;

    try {
      await this.call('initialize', {
        clientInfo: {
          name: 'codex-web-console',
          version: '0.1.0'
        },
        capabilities: {}
      }, 30000);

      await this.notify('initialized', {});

      const threadParams = {
        cwd: process.cwd(),
        approvalPolicy: 'never',
        sandbox: 'danger-full-access'
      };

      if (defaultCodexModel) {
        threadParams.model = defaultCodexModel;
      }

      let threadResult;
      let resumed = false;

      if (this.forceFreshThread) {
        await clearSavedThread(process.cwd());
      }

      const threadIdToResume = this.requestedThreadId
        || (!this.forceFreshThread ? (await getSavedThread(process.cwd()))?.threadId : undefined);

      if (!this.forceFreshThread && threadIdToResume) {
        try {
          threadResult = await this.call('thread/resume', {
            ...threadParams,
            threadId: threadIdToResume
          }, 30000);
          resumed = true;
        } catch (error) {
          if (!this.requestedThreadId) {
            await clearSavedThread(process.cwd());
          }
        }
      }

      if (!threadResult) {
        threadResult = await this.call('thread/start', threadParams, 30000);
      }

      const thread = threadResult && typeof threadResult === 'object' ? threadResult.thread : null;
      this.threadId = thread && typeof thread.id === 'string' ? thread.id : undefined;

      if (!this.threadId) {
        throw new Error('Codex did not return a thread id.');
      }

      this.forceFreshThread = false;
      this.requestedThreadId = undefined;
      await saveThread(process.cwd(), this.threadId);
      this.initialized = true;
      this.initializing = false;

      if (resumed) {
        this.sendHistory(thread);
      }

      this.send({
        type: 'activity',
        label: 'Ready',
        status: 'online'
      });

      const queuedPrompts = this.pendingPrompts.splice(0);
      for (const promptText of queuedPrompts) {
        await this.startTurn(promptText);
      }
      return {
        threadId: this.threadId
      };
    } catch (error) {
      this.initializing = false;
      this.send({
        type: 'error',
        message: `Codex app-server initialization failed: ${error.message}`
      });
      this.send({
        type: 'activity',
        label: 'Error',
        status: 'offline'
      });
      throw error;
    }
  }

  async startTurn(promptText) {
    const turnParams = {
      threadId: this.threadId,
      input: [{ type: 'text', text: promptText }],
      cwd: process.cwd(),
      approvalPolicy: 'never',
      sandboxPolicy: { type: 'dangerFullAccess' }
    };

    if (defaultCodexModel) {
      turnParams.model = defaultCodexModel;
    }

    try {
      this.send({
        type: 'activity',
        label: 'Running',
        status: 'busy'
      });

      this.startingTurn = true;
      const turnResult = await this.call('turn/start', turnParams, 120000);
      const turn = turnResult && typeof turnResult === 'object' ? turnResult.turn : null;
      this.currentTurnId = turn && typeof turn.id === 'string' ? turn.id : this.currentTurnId;
      this.startingTurn = false;
      if (this.threadId) {
        await saveThread(process.cwd(), this.threadId);
      }
      return {
        threadId: this.threadId,
        turnId: this.currentTurnId
      };
    } catch (error) {
      this.currentTurnId = undefined;
      this.startingTurn = false;
      this.send({
        type: 'error',
        message: `Failed to start Codex turn: ${error.message}`
      });
      this.send({
        type: 'activity',
        label: 'Error',
        status: 'offline'
      });
    }
  }

  handleNotification(method, params) {
    if (this.hasForeignThread(params)) {
      return;
    }

    if (method === 'item/started') {
      const item = params.item;
      if (item && item.type === 'agentMessage' && typeof item.id === 'string') {
        this.agentTextByItemId.set(item.id, '');
        return;
      }

      if (item && item.type === 'reasoning') {
        this.handleReasoningStarted(item);
        return;
      }

      if (item && item.type === 'commandExecution') {
        this.handleCommandStarted(item);
        return;
      }

      if (item && item.type === 'fileChange') {
        this.handleFileChangeStarted(item);
        return;
      }

      if (item && item.type === 'webSearch') {
        this.handleSimpleToolStarted(item, 'web_search', 'Web search', {
          query: typeof item.query === 'string' ? item.query : ''
        });
        return;
      }

      if (item && item.type === 'collabAgentToolCall') {
        this.handleCollabAgentStarted(item);
        return;
      }

      if (item && item.type === 'mcpToolCall') {
        this.handleSimpleToolStarted(item, 'mcp_tool', `${item.server || 'mcp'}:${item.tool || 'tool'}`, {
          server: item.server || '',
          tool: item.tool || '',
          arguments: item.arguments || {}
        });
      }
      return;
    }

    if (method === 'item/agentMessage/delta') {
      this.handleAgentTextDelta(params.itemId, params.delta);
      return;
    }

    if (method === 'item/delta') {
      this.handleGenericItemDelta(params);
      return;
    }

    if (
      method === 'item/reasoning/summaryTextDelta' ||
      method === 'item/reasoning/summaryPartAdded'
    ) {
      this.handleReasoningDelta(params);
      return;
    }

    if (
      method === 'item/reasoning/textDelta' ||
      method === 'item/reasoning/delta'
    ) {
      this.handleReasoningStatus(params);
      return;
    }

    if (method === 'item/commandExecution/outputDelta') {
      this.handleCommandOutputDelta(params);
      return;
    }

    if (method === 'item/commandExecution/terminalInteraction') {
      this.handleToolProgress(params.itemId);
      return;
    }

    if (method === 'item/fileChange/outputDelta') {
      this.handleToolProgress(params.itemId);
      return;
    }

    if (method === 'item/completed') {
      this.handleItemCompleted(params.item);
      return;
    }

    if (method === 'turn/started') {
      const turn = params.turn;
      this.currentTurnId = turn && typeof turn.id === 'string' ? turn.id : this.currentTurnId;
      this.startingTurn = false;
      this.currentTurnStartedAt = this.timestampFromSeconds(turn?.startedAt) || Date.now();
      this.send({
        type: 'turn_started',
        turnId: this.currentTurnId,
        startedAt: this.currentTurnStartedAt,
        officialStartedAt: this.timestampFromSeconds(turn?.startedAt)
      });
      this.send({
        type: 'activity',
        label: 'Running',
        status: 'busy'
      });
      return;
    }

    if (method === 'turn/completed') {
      const turn = params.turn && typeof params.turn === 'object' ? params.turn : {};
      const officialStartedAt = this.timestampFromSeconds(turn.startedAt);
      const officialCompletedAt = this.timestampFromSeconds(turn.completedAt);
      const completedAt = officialCompletedAt || Date.now();
      const officialDurationMs = typeof turn.durationMs === 'number' ? turn.durationMs : undefined;
      const durationMs = officialDurationMs !== undefined
        ? officialDurationMs
        : (this.currentTurnStartedAt ? completedAt - this.currentTurnStartedAt : undefined);
      this.currentTurnId = undefined;
      this.startingTurn = false;
      this.currentTurnStartedAt = undefined;
      this.send({
        type: 'turn_completed',
        turnId: typeof turn.id === 'string' ? turn.id : undefined,
        status: typeof turn.status === 'string' ? turn.status : 'completed',
        durationMs,
        officialStartedAt,
        officialCompletedAt,
        officialDurationMs,
        completedAt
      });
      this.send({
        type: 'activity',
        label: 'Ready',
        status: 'online'
      });
      this.startNextQueuedPrompt().catch((error) => {
        this.send({
          type: 'error',
          message: `Failed to start queued Codex turn: ${error.message}`
        });
      });
      return;
    }

    if (method === 'thread/tokenUsage/updated') {
      this.handleTokenUsageUpdated(params);
      return;
    }

    if (method === 'thread/status/changed') {
      const status = typeof params.status === 'string' ? params.status : '';
      if (status) {
        this.send({
          type: 'activity',
          label: status,
          status: status === 'running' ? 'busy' : 'pending'
        });
      }
    }
  }

  handleTokenUsageUpdated(params) {
    const event = normalizeTokenUsageUpdate(params, {
      threadId: this.threadId,
      turnId: this.currentTurnId
    });
    if (event) {
      this.send(event);
    }
  }

  hasForeignThread(params) {
    const threadId = params && typeof params.threadId === 'string' ? params.threadId : '';
    return Boolean(threadId && this.threadId && threadId !== this.threadId);
  }

  sendHistory(thread) {
    const entries = this.normalizeThreadHistory(thread);

    if (entries.length === 0) {
      return;
    }

    this.send({
      type: 'history_restored',
      threadId: this.threadId,
      entries
    });
  }

  normalizeThreadHistory(thread) {
    const turns = Array.isArray(thread?.turns) ? thread.turns : [];
    const entries = [];

    for (const turn of turns) {
      const items = Array.isArray(turn?.items) ? turn.items : [];
      const assistantMessages = [];
      const workingMessages = [];
      const tools = [];
      const timestamp = this.timestampFromSeconds(turn?.startedAt);

      for (const item of items) {
        if (!item || typeof item !== 'object') {
          continue;
        }

        if (item.type === 'userMessage') {
          const text = this.extractHistoryUserText(item);
          if (text && !this.isAutomatedAi4mlPrompt(text)) {
            entries.push({
              type: 'message',
              role: 'user',
              text,
              timestamp
            });
          }
          continue;
        }

        if (item.type === 'agentMessage') {
          const text = typeof item.text === 'string' ? item.text.trim() : '';
          if (!text) {
            continue;
          }

          if (item.phase === 'commentary') {
            workingMessages.push(text);
          } else {
            assistantMessages.push(text);
          }
          continue;
        }

        const tool = this.normalizeHistoryTool(item);
        if (tool) {
          tools.push(tool);
        }
      }

      if (workingMessages.length > 0 || tools.length > 0) {
        entries.push({
          type: 'working',
          text: workingMessages.join('\n\n'),
          tools,
          durationMs: typeof turn?.durationMs === 'number' ? turn.durationMs : undefined,
          timestamp
        });
      }

      for (const text of assistantMessages) {
        entries.push({
          type: 'message',
          role: 'assistant',
          text,
          timestamp: this.timestampFromSeconds(turn?.completedAt) || timestamp
        });
      }
    }

    return entries;
  }

  extractHistoryUserText(item) {
    if (typeof item.text === 'string') {
      return item.text.trim();
    }

    if (typeof item.message === 'string') {
      return item.message.trim();
    }

    if (Array.isArray(item.content)) {
      return item.content
        .map((part) => {
          if (typeof part === 'string') {
            return part;
          }
          if (typeof part?.text === 'string') {
            return part.text;
          }
          if (Array.isArray(part?.text_elements)) {
            return part.text_elements
              .map((element) => (typeof element?.text === 'string' ? element.text : ''))
              .filter(Boolean)
              .join('');
          }
          return '';
        })
        .filter(Boolean)
        .join('\n')
        .trim();
    }

    return '';
  }

  isAutomatedAi4mlPrompt(text) {
    return typeof text === 'string' && text.trimStart().startsWith('#AI4ML_');
  }

  normalizeHistoryTool(item) {
    if (item.type === 'commandExecution') {
      return {
        tool: 'command',
        title: item.status === 'failed' ? 'Command failed' : 'Ran command',
        command: this.commandToString(item.command),
        cwd: typeof item.cwd === 'string' ? item.cwd : undefined,
        stdout: typeof item.stdout === 'string' ? item.stdout : '',
        stderr: typeof item.stderr === 'string' ? item.stderr : '',
        exitCode: typeof item.exitCode === 'number' ? item.exitCode : undefined,
        status: typeof item.status === 'string' ? item.status : 'completed',
        durationMs: typeof item.durationMs === 'number' ? item.durationMs : undefined
      };
    }

    if (item.type === 'fileChange') {
      return {
        tool: 'file_change',
        title: item.status === 'failed' ? 'File change failed' : 'Changed files',
        changes: Array.isArray(item.changes) ? item.changes : [],
        status: typeof item.status === 'string' ? item.status : 'completed',
        durationMs: typeof item.durationMs === 'number' ? item.durationMs : undefined
      };
    }

    if (item.type === 'webSearch') {
      return {
        tool: 'web_search',
        title: 'Web search',
        input: {
          query: typeof item.query === 'string' ? item.query : ''
        },
        output: this.extractToolSummary(item),
        status: typeof item.status === 'string' ? item.status : 'completed'
      };
    }

    if (item.type === 'mcpToolCall') {
      return {
        tool: 'mcp_tool',
        title: `${item.server || 'mcp'}:${item.tool || 'tool'}`,
        input: {
          server: item.server || '',
          tool: item.tool || '',
          arguments: item.arguments || {}
        },
        output: this.extractToolSummary(item),
        status: typeof item.status === 'string' ? item.status : 'completed'
      };
    }

    if (item.type === 'collabAgentToolCall') {
      const collabAgent = this.normalizeCollabAgentToolCall(item);
      return {
        tool: 'collab_agent',
        title: this.collabAgentTitle(collabAgent.tool, collabAgent.status, collabAgent),
        output: this.collabAgentSummary(collabAgent),
        status: collabAgent.status,
        collabAgent
      };
    }

    return null;
  }

  timestampFromSeconds(value) {
    return typeof value === 'number' && Number.isFinite(value) && value > 0
      ? value * 1000
      : undefined;
  }
}

Object.assign(AppServerRunner.prototype, messageEventHandlers, toolEventHandlers);
