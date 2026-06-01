import { elements, state } from '../state.js';
import {
  cleanOutput,
  createLucidePlaceholder,
  formatDuration,
  normalizeChangeKind,
  refreshIcons,
  refreshIconsNow,
  toolIcon
} from '../utils.js';
import { scrollConversationToBottom } from '../ui.js';
import { consumePendingAssistantText, createMessage, setMessageContent } from './messages.js';

export function startWorkingBlock(startedAt, title = 'Working') {
  if (state.activeWorkingBlock) {
    return state.activeWorkingBlock;
  }

  const article = document.createElement('article');
  article.className = 'timeline-block working-block is-running is-collapsed';
  article.dataset.role = 'working';

  const header = document.createElement('button');
  header.className = 'timeline-header working-header';
  header.type = 'button';
  header.setAttribute('aria-expanded', 'false');
  header.innerHTML = `
    <span class="timeline-header-main">
      <i data-lucide="loader-2"></i>
      <strong>${title}</strong>
    </span>
    <span class="timeline-duration">0s</span>
    <i data-lucide="chevron-right"></i>
  `;

  const body = createTimelineBody('working-body');
  article.appendChild(header);
  elements.conversation.appendChild(article);

  header.addEventListener('click', () => toggleTimelineBlock(article, header, body));

  state.activeWorkingBlock = article;
  state.activeWorkingBody = body;
  state.activeWorkingContent = null;
  state.activeWorkingStartedAt = startedAt || Date.now();
  startWorkingTimer();
  refreshIcons();
  scrollConversationToBottom();
  return article;
}

export function appendWorkingText(text) {
  const cleaned = cleanOutput(text).trim();
  if (!cleaned) {
    return;
  }

  const content = ensureWorkingContent();
  if (!content) {
    return;
  }

  const existing = content.textContent.trim();
  content.textContent = existing ? `${existing}\n${cleaned}` : cleaned;
  scrollConversationToBottom();
}

export function movePendingAssistantToWorking() {
  const text = consumePendingAssistantText();
  if (!text) {
    return false;
  }

  const message = createMessage('assistant', 'Codex', 'bot');
  message.classList.add('working-message');
  setMessageContent(message, text);
  appendToWorkingBody(message);
  return true;
}

export function finishWorkingBlock(durationMs, options = {}) {
  stopWorkingTimer();

  if (!state.activeWorkingBlock) {
    return;
  }

  const elapsed = typeof durationMs === 'number'
    ? durationMs
    : (state.activeWorkingStartedAt ? Date.now() - state.activeWorkingStartedAt : 0);
  const duration = state.activeWorkingBlock.querySelector('.timeline-duration');
  const title = state.activeWorkingBlock.querySelector('.timeline-header-main strong');

  if (duration) {
    duration.textContent = `Worked for ${formatDuration(elapsed)}`;
  }

  if (title) {
    title.textContent = options.title || 'Worked';
  }

  state.activeWorkingBlock.classList.add('is-complete');
  if (options.interrupted) {
    state.activeWorkingBlock.classList.add('is-error');
  }
  state.activeWorkingBlock.classList.remove('is-running');
  markOpenToolBlocksEnded();
  state.activeWorkingBlock = null;
  state.activeWorkingBody = null;
  state.activeWorkingContent = null;
  state.activeWorkingStartedAt = null;
}

export function addHistoryWorkingBlock(entry) {
  const previousRunState = state.runState;
  state.runState = 'running';
  startWorkingBlock(entry.timestamp || Date.now(), 'Working');

  if (entry.text) {
    appendWorkingText(entry.text);
  }

  if (Array.isArray(entry.tools)) {
    for (const tool of entry.tools) {
      const toolUseId = `history-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const startedAt = entry.timestamp || Date.now();
      renderToolStart({
        toolUseId,
        tool: tool.tool,
        title: tool.title,
        command: tool.command,
        cwd: tool.cwd,
        changes: tool.changes,
        collabAgent: tool.collabAgent,
        startedAt
      });
      renderToolResult({
        toolUseId,
        tool: tool.tool,
        title: tool.title,
        stdout: tool.stdout,
        stderr: tool.stderr,
        output: tool.output,
        exitCode: tool.exitCode,
        status: tool.status,
        durationMs: tool.durationMs,
        changes: tool.changes,
        collabAgent: tool.collabAgent
      });
      state.toolBlocks.delete(toolUseId);
    }
  }

  finishWorkingBlock(entry.durationMs);
  state.runState = previousRunState;
}

export function stopWorkingTimer() {
  if (!state.workingTimer) {
    return;
  }

  window.clearInterval(state.workingTimer);
  state.workingTimer = null;
}

export function renderToolStart(message) {
  movePendingAssistantToWorking();
  const toolUseId = message.toolUseId || `tool-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  if (state.toolBlocks.has(toolUseId)) {
    updateToolProgress({ toolUseId, elapsedMs: 0 });
    return state.toolBlocks.get(toolUseId);
  }

  const article = document.createElement('article');
  article.className = `timeline-block tool-block tool-${message.tool || 'generic'} is-collapsed`;
  article.dataset.role = 'tool';

  const header = document.createElement('button');
  header.className = 'timeline-header tool-header';
  header.type = 'button';
  header.setAttribute('aria-expanded', 'false');
  header.innerHTML = `
    <span class="timeline-header-main">
      <i data-lucide="${toolIcon(message.tool)}"></i>
      <strong>${message.title || 'Running tool'}</strong>
    </span>
    <span class="timeline-duration">Running</span>
    <i data-lucide="chevron-right"></i>
  `;

  const body = createTimelineBody('tool-body');

  if (message.command) {
    const command = document.createElement('pre');
    command.className = 'tool-command';
    command.textContent = message.command;
    body.appendChild(command);
  }

  if (message.cwd) {
    const cwd = document.createElement('div');
    cwd.className = 'tool-cwd';
    cwd.textContent = message.cwd;
    body.appendChild(cwd);
  }

  if (Array.isArray(message.changes) && message.changes.length > 0) {
    body.appendChild(createChangeList(message.changes));
  }

  if (message.collabAgent) {
    body.appendChild(createCollabAgentDetails(message.collabAgent));
  }

  const output = document.createElement('pre');
  output.className = 'tool-output';
  output.hidden = true;
  body.appendChild(output);

  article.appendChild(header);
  if (!appendToWorkingBody(article)) {
    return null;
  }

  header.addEventListener('click', () => toggleTimelineBlock(article, header, body));

  state.toolBlocks.set(toolUseId, {
    article,
    body,
    footer: null,
    header,
    output,
    startedAt: message.startedAt || Date.now()
  });

  refreshIcons();
  scrollConversationToBottom();
  return state.toolBlocks.get(toolUseId);
}

export function appendToolOutput(message) {
  const block = getOrCreateToolBlock(message.toolUseId);
  if (!block) {
    return;
  }

  const cleaned = cleanOutput(message.data || '');
  if (!cleaned.trim()) {
    return;
  }

  block.output.hidden = false;
  block.output.textContent += cleaned;
  block.article.classList.add('has-output');
  scrollConversationToBottom();
}

export function updateToolProgress(message) {
  const block = state.toolBlocks.get(message.toolUseId);
  if (!block) {
    return;
  }

  const duration = block.header.querySelector('.timeline-duration');
  if (duration) {
    duration.textContent = `${formatDuration(message.elapsedMs || Date.now() - block.startedAt)}`;
  }
}

export function renderToolResult(message) {
  const block = getOrCreateToolBlock(message.toolUseId, message);
  if (!block) {
    return;
  }

  const duration = block.header.querySelector('.timeline-duration');
  const title = block.header.querySelector('.timeline-header-main strong');

  if (title) {
    title.textContent = message.title || 'Tool completed';
  }

  if (duration) {
    duration.textContent = formatDuration(message.durationMs || Date.now() - block.startedAt);
  }

  const outputText = getToolOutputText(message);
  if (outputText.trim()) {
    block.output.hidden = false;
    block.output.textContent = outputText;
    block.article.classList.add('has-output');
  } else {
    block.output.textContent = '';
    block.output.hidden = true;
    block.article.classList.remove('has-output');
  }

  if (message.collabAgent) {
    replaceCollabAgentDetails(block.body, message.collabAgent);
  }

  if (message.exitCode !== undefined) {
    if (!block.footer) {
      block.footer = document.createElement('div');
      block.footer.className = 'tool-footer';
      block.body.appendChild(block.footer);
    }
    block.footer.textContent = `exit ${message.exitCode}`;
  }

  block.article.classList.add('is-complete');
  if (message.status === 'failed' || (typeof message.exitCode === 'number' && message.exitCode !== 0)) {
    block.article.classList.add('is-error');
  }

  scrollConversationToBottom();
}

function startWorkingTimer() {
  stopWorkingTimer();
  updateWorkingDuration();
  state.workingTimer = window.setInterval(updateWorkingDuration, 1000);
}

function updateWorkingDuration() {
  if (!state.activeWorkingBlock || !state.activeWorkingStartedAt) {
    return;
  }

  const duration = state.activeWorkingBlock.querySelector('.timeline-duration');
  if (duration) {
    duration.textContent = formatDuration(Date.now() - state.activeWorkingStartedAt);
  }
}

function getOrCreateToolBlock(toolUseId, message = {}) {
  if (toolUseId && state.toolBlocks.has(toolUseId)) {
    return state.toolBlocks.get(toolUseId);
  }

  return renderToolStart({
    toolUseId,
    tool: message.tool || 'generic',
    title: message.title || 'Tool',
    command: message.command,
    cwd: message.cwd,
    changes: message.changes,
    startedAt: Date.now()
  });
}

function ensureWorkingContent() {
  if (state.runState !== 'running' && !state.activeWorkingBlock) {
    return null;
  }

  startWorkingBlock();
  const content = state.activeWorkingContent || document.createElement('pre');

  if (!state.activeWorkingContent) {
    content.className = 'working-content';
    appendToWorkingBody(content);
    state.activeWorkingContent = content;
  } else {
    syncWorkingBodyAttachment();
  }

  return content;
}

function appendToWorkingBody(node) {
  if (state.runState !== 'running' && !state.activeWorkingBlock) {
    return false;
  }

  startWorkingBlock();
  state.activeWorkingBody.appendChild(node);
  syncWorkingBodyAttachment();
  scrollConversationToBottom();
  return true;
}

function syncWorkingBodyAttachment() {
  if (!state.activeWorkingBlock || !state.activeWorkingBody) {
    return;
  }

  const header = state.activeWorkingBlock.querySelector('.timeline-header');
  const expanded = header && header.getAttribute('aria-expanded') === 'true';

  if (expanded && !state.activeWorkingBody.isConnected) {
    state.activeWorkingBlock.appendChild(state.activeWorkingBody);
  }

  if (!expanded && state.activeWorkingBody.isConnected) {
    state.activeWorkingBody.remove();
  }
}

function toggleTimelineBlock(article, header, body) {
  const expanded = header.getAttribute('aria-expanded') === 'true';
  setTimelineExpanded(article, header, body, !expanded);
}

function setTimelineExpanded(article, header, body, expanded) {
  if (!article || !header || !body) {
    return;
  }

  header.setAttribute('aria-expanded', String(expanded));
  if (expanded && !body.isConnected) {
    article.appendChild(body);
  }

  body.hidden = !expanded;
  body.style.display = expanded ? '' : 'none';
  body.classList.toggle('is-collapsed', !expanded);
  article.classList.toggle('is-collapsed', !expanded);

  if (!expanded && body.isConnected) {
    body.remove();
  }

  const icon = header.querySelector('svg:last-child');
  if (icon) {
    icon.replaceWith(createLucidePlaceholder(expanded ? 'chevron-down' : 'chevron-right'));
  }

  refreshIconsNow();
}

function createTimelineBody(className) {
  const body = document.createElement('div');
  body.className = `timeline-body ${className} is-collapsed`;
  body.hidden = true;
  body.style.display = 'none';
  return body;
}

function createChangeList(changes) {
  const list = document.createElement('ul');
  list.className = 'tool-changes';
  for (const change of changes) {
    const item = document.createElement('li');
    item.textContent = `${normalizeChangeKind(change.kind)} ${change.path || ''}`.trim();
    list.appendChild(item);
  }
  return list;
}

function createCollabAgentDetails(collabAgent) {
  const details = document.createElement('div');
  details.className = 'collab-agent-details';

  const meta = document.createElement('dl');
  meta.className = 'collab-agent-meta';
  appendDefinition(meta, 'Action', formatCollabAgentTool(collabAgent.tool));
  appendDefinition(meta, 'Status', formatCollabAgentStatus(collabAgent.status));

  if (collabAgent.model) {
    appendDefinition(meta, 'Model', collabAgent.model);
  }

  if (collabAgent.reasoningEffort) {
    appendDefinition(meta, 'Reasoning', collabAgent.reasoningEffort);
  }

  if (collabAgent.senderThreadId) {
    appendDefinition(meta, 'Sender', collabAgent.senderThreadId);
  }

  if (Array.isArray(collabAgent.receiverThreadIds) && collabAgent.receiverThreadIds.length > 0) {
    appendDefinition(meta, 'Agents', formatAgentList(collabAgent.receiverThreadIds));
  }

  details.appendChild(meta);

  if (collabAgent.prompt) {
    const promptLabel = document.createElement('div');
    promptLabel.className = 'collab-agent-section-label';
    promptLabel.textContent = 'Task prompt';
    details.appendChild(promptLabel);

    const prompt = document.createElement('pre');
    prompt.className = 'collab-agent-prompt';
    prompt.textContent = collabAgent.prompt;
    details.appendChild(prompt);
  }

  const stateEntries = Object.entries(collabAgent.agentsStates || {});
  if (stateEntries.length > 0) {
    const states = document.createElement('ul');
    states.className = 'collab-agent-states';

    for (const [agentId, agentState] of stateEntries) {
      const item = document.createElement('li');
      const id = document.createElement('code');
      id.textContent = agentId;
      const status = document.createElement('span');
      status.className = 'collab-agent-state';
      status.dataset.status = agentState.status || 'unknown';
      status.textContent = formatAgentState(agentState.status);
      item.append(id, status);

      if (agentState.message) {
        const message = document.createElement('small');
        message.textContent = agentState.message;
        item.appendChild(message);
      }

      states.appendChild(item);
    }

    details.appendChild(states);
  }

  return details;
}

function replaceCollabAgentDetails(body, collabAgent) {
  const existing = body.querySelector('.collab-agent-details');
  const replacement = createCollabAgentDetails(collabAgent);

  if (existing) {
    existing.replaceWith(replacement);
    return;
  }

  const output = body.querySelector('.tool-output');
  if (output) {
    body.insertBefore(replacement, output);
    return;
  }

  body.appendChild(replacement);
}

function appendDefinition(list, label, value) {
  const row = document.createElement('div');
  const term = document.createElement('dt');
  const description = document.createElement('dd');
  term.textContent = label;
  description.textContent = value;
  row.append(term, description);
  list.appendChild(row);
}

function formatCollabAgentTool(tool) {
  const labels = {
    spawnAgent: 'Create child agent',
    sendInput: 'Send follow-up to child agent',
    resumeAgent: 'Resume child agent',
    wait: 'Wait for child agents',
    closeAgent: 'Close child agent'
  };
  return labels[tool] || tool || 'Agent action';
}

function formatCollabAgentStatus(status) {
  const labels = {
    inProgress: 'Running',
    completed: 'Completed',
    failed: 'Failed'
  };
  return labels[status] || status || 'Unknown';
}

function formatAgentState(status) {
  const labels = {
    pendingInit: 'Starting',
    running: 'Running',
    interrupted: 'Interrupted',
    completed: 'Completed',
    errored: 'Errored',
    shutdown: 'Closed',
    notFound: 'Not found'
  };
  return labels[status] || status || 'Unknown';
}

function formatAgentList(threadIds) {
  return threadIds
    .map((threadId, index) => `Agent ${index + 1}: ${threadId}`)
    .join('\n');
}

function markOpenToolBlocksEnded() {
  for (const [, block] of state.toolBlocks) {
    if (!block.article || block.article.classList.contains('is-complete')) {
      continue;
    }

    const duration = block.header.querySelector('.timeline-duration');
    const title = block.header.querySelector('.timeline-header-main strong');
    if (duration) {
      duration.textContent = formatDuration(Date.now() - block.startedAt);
    }
    if (title) {
      title.textContent = `${title.textContent || 'Tool'} ended`;
    }

    block.article.classList.add('is-complete');
  }
}

function getToolOutputText(message) {
  const outputParts = [];
  if (typeof message.stdout === 'string' && message.stdout.trim()) {
    outputParts.push(message.stdout);
  }
  if (typeof message.stderr === 'string' && message.stderr.trim()) {
    outputParts.push(message.stderr);
  }
  if (typeof message.output === 'string' && message.output.trim()) {
    outputParts.push(message.output);
  }
  return cleanOutput(outputParts.join('\n')).trimEnd();
}
