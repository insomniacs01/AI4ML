
import { createSessionId, extractText } from '../utils.js';

export const messageEventHandlers = {
  handleAgentTextDelta(itemId, delta) {
    const text = typeof delta === 'string' ? delta : extractText(delta);

    if (!text) {
      return;
    }

    if (typeof itemId === 'string') {
      const currentText = this.agentTextByItemId.get(itemId) || '';
      this.agentTextByItemId.set(itemId, `${currentText}${text}`);
    }

    this.send({
      type: 'assistant_delta',
      itemId: typeof itemId === 'string' ? itemId : undefined,
      data: text
    });
  },

  handleGenericItemDelta(params) {
    const delta = params.delta;

    if (typeof delta === 'string') {
      this.handleAgentTextDelta(params.itemId, delta);
      return;
    }

    if (!delta || typeof delta !== 'object') {
      return;
    }

    if (delta.type === 'text_delta' || delta.type === 'text') {
      this.handleAgentTextDelta(params.itemId, delta.text);
      return;
    }

    this.handleAgentTextDelta(params.itemId, extractText(delta));
  },

  handleItemCompleted(item) {
    if (!item || typeof item !== 'object') {
      return;
    }

    if (item.type === 'commandExecution') {
      this.handleCommandCompleted(item);
      return;
    }

    if (item.type === 'fileChange') {
      this.handleFileChangeCompleted(item);
      return;
    }

    if (item.type === 'webSearch') {
      this.handleSimpleToolCompleted(item, item.status === 'failed');
      return;
    }

    if (item.type === 'collabAgentToolCall') {
      this.handleCollabAgentCompleted(item);
      return;
    }

    if (item.type === 'mcpToolCall') {
      this.handleSimpleToolCompleted(item, item.status === 'failed');
      return;
    }

    if (item.type === 'reasoning') {
      this.handleReasoningCompleted(item);
      return;
    }

    if (item.type !== 'agentMessage') {
      return;
    }

    const finalText = typeof item.text === 'string' ? item.text : extractText(item);
    const itemId = typeof item.id === 'string' ? item.id : undefined;
    const streamedText = itemId ? this.agentTextByItemId.get(itemId) || '' : '';

    if (finalText && !streamedText) {
      this.send({
        type: 'assistant_delta',
        itemId,
        data: finalText
      });
    } else if (finalText && streamedText && finalText.startsWith(streamedText)) {
      const missingSuffix = finalText.slice(streamedText.length);
      if (missingSuffix) {
        this.send({
          type: 'assistant_delta',
          itemId,
          data: missingSuffix
        });
      }
    }

    if (itemId) {
      this.agentTextByItemId.delete(itemId);
    }

    this.send({
      type: 'assistant_done',
      itemId
    });
  },

  handleReasoningStarted(item) {
    const itemId = typeof item.id === 'string' ? item.id : createSessionId();
    const initialText = this.getReasoningSummary(item);
    this.reasoningTextByItemId.set(itemId, initialText);
    this.send({
      type: 'working_start',
      itemId,
      title: 'Working',
      startedAt: Date.now()
    });

    if (initialText) {
      this.send({
        type: 'working_delta',
        itemId,
        data: initialText
      });
    }
  },

  handleReasoningDelta(params) {
    const itemId = typeof params.itemId === 'string' ? params.itemId : undefined;
    const text = this.getReasoningSummary(params);

    if (!itemId || !text.trim()) {
      return;
    }

    const currentText = this.reasoningTextByItemId.get(itemId) || '';
    this.reasoningTextByItemId.set(itemId, `${currentText}${text}`);
    this.send({
      type: 'working_delta',
      itemId,
      data: text
    });
  },

  handleReasoningStatus(params) {
    const itemId = typeof params.itemId === 'string' ? params.itemId : undefined;

    if (!itemId || this.reasoningTextByItemId.has(itemId)) {
      return;
    }

    this.reasoningTextByItemId.set(itemId, '');
    this.send({
      type: 'working_start',
      itemId,
      title: 'Working',
      startedAt: Date.now()
    });
  },

  handleReasoningCompleted(item) {
    const itemId = typeof item.id === 'string' ? item.id : undefined;
    const finalText = this.getReasoningSummary(item);
    const streamedText = itemId ? this.reasoningTextByItemId.get(itemId) || '' : '';

    if (itemId && finalText.trim() && !streamedText) {
      this.send({
        type: 'working_delta',
        itemId,
        data: finalText
      });
    }

    if (itemId) {
      this.reasoningTextByItemId.delete(itemId);
    }

    this.send({
      type: 'working_done',
      itemId,
      completedAt: Date.now()
    });
  },

  getReasoningSummary(value) {
    if (!value || typeof value !== 'object') {
      return '';
    }

    const candidates = [
      value.summary,
      value.summaryText,
      value.delta,
      value.part
    ];

    return candidates
      .map((candidate) => (typeof candidate === 'string' ? candidate : extractText(candidate)))
      .find((text) => text && text.trim()) || '';
  }
};
