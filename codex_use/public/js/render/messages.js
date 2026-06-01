import { elements, state } from '../state.js';
import { cleanOutput, formatTime, refreshIcons } from '../utils.js';
import { scrollConversationToBottom } from '../ui.js';
import { renderMarkdownInto } from '../markdown.js';

export function appendRaw(chunk) {
  state.rawText += chunk;

  if (state.rawText.length > 60000) {
    state.rawText = state.rawText.slice(-60000);
  }

  elements.rawLog.textContent = state.rawText;
  elements.rawLog.scrollTop = elements.rawLog.scrollHeight;
}

export function queueOutput(chunk) {
  const cleaned = cleanOutput(chunk);
  if (!cleaned.trim()) {
    return;
  }

  state.outputBuffer += cleaned;
  window.clearTimeout(state.outputFlushTimer);
  state.outputFlushTimer = window.setTimeout(flushOutput, 140);
}

export function flushOutput() {
  window.clearTimeout(state.outputFlushTimer);

  const text = state.outputBuffer.trim();
  if (!text) {
    state.outputBuffer = '';
    return;
  }

  appendAssistantText(text);
  state.outputBuffer = '';
}

export function finishAssistantMessage() {
  if (state.streamingMessage) {
    const content = state.streamingMessage.querySelector('.message-content');
    const markdown = content ? (content.dataset.markdown || '').trim() : '';
    if (!markdown) {
      state.streamingMessage.remove();
      state.streamingMessage = null;
      return;
    }

    state.streamingMessage.classList.remove('is-streaming');
    state.streamingMessage = null;
  }
}

export function appendAssistantText(text) {
  const cleaned = cleanOutput(text).trim();
  if (!cleaned) {
    return;
  }

  const message = state.streamingMessage || startAssistantMessage();
  appendTextToMessage(message, cleaned);
}

export function appendPendingAssistantText(chunk) {
  const cleaned = cleanOutput(chunk);
  if (!cleaned.trim()) {
    return;
  }

  state.pendingAssistantText += cleaned;
}

export function markPendingAssistantMessageDone() {
  if (!state.pendingAssistantText.trim() || state.pendingAssistantText.endsWith('\n\n')) {
    return;
  }

  state.pendingAssistantText = `${state.pendingAssistantText.trimEnd()}\n\n`;
}

export function consumePendingAssistantText() {
  const text = state.pendingAssistantText.trim();
  state.pendingAssistantText = '';
  return text;
}

export function flushPendingAssistantMessage() {
  const text = consumePendingAssistantText();
  if (!text) {
    return false;
  }

  appendAssistantText(text);
  finishAssistantMessage();
  return true;
}

export function addUserMessage(text, timestamp) {
  const article = createMessage('user', 'You', 'user-round', timestamp);
  setMessageContent(article, text);
  elements.conversation.appendChild(article);
  scrollConversationToBottom();
}

export function addAssistantMessage(text, timestamp) {
  const article = createMessage('assistant', 'Codex', 'bot', timestamp);
  setMessageContent(article, text);
  elements.conversation.appendChild(article);
  scrollConversationToBottom();
}

export function addSystemMessage(text, tone, timestamp) {
  const article = createMessage('system', 'Console', tone === 'warning' ? 'triangle-alert' : 'info', timestamp);
  article.classList.add(`message-${tone || 'system'}`);
  setMessageContent(article, text);
  elements.conversation.appendChild(article);
  scrollConversationToBottom();
}

function startAssistantMessage() {
  const article = createMessage('assistant', 'Codex', 'bot');
  article.classList.add('is-streaming');
  setMessageContent(article, '');
  elements.conversation.appendChild(article);
  state.streamingMessage = article;
  scrollConversationToBottom();
  return article;
}

export function createMessage(role, label, icon, timestamp) {
  const article = document.createElement('article');
  article.className = `message message-${role}`;
  article.dataset.role = role;

  const avatar = document.createElement('div');
  avatar.className = 'message-avatar';
  avatar.innerHTML = `<i data-lucide="${icon}"></i>`;

  const body = document.createElement('div');
  body.className = 'message-body';

  const meta = document.createElement('div');
  meta.className = 'message-meta';
  meta.textContent = `${label} · ${formatTime(timestamp || new Date().toISOString())}`;

  const content = document.createElement('div');
  content.className = 'message-content';

  body.append(meta, content);
  article.append(avatar, body);
  refreshIcons();

  return article;
}

function appendTextToMessage(message, text) {
  const content = message.querySelector('.message-content');
  const existing = (content.dataset.markdown || '').trim();
  setMessageContent(message, existing ? `${existing}\n${text}` : text);
  scrollConversationToBottom();
}

export function setMessageContent(message, markdownText) {
  const content = message.querySelector('.message-content');
  renderMarkdownInto(content, markdownText);
}
