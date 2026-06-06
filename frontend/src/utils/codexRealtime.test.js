import { describe, expect, it } from 'vitest'
import { applyCodexRealtimeEvent, createCodexRealtimeState, shouldApplyRealtimeTaskPatch } from './codexRealtime'

describe('codex realtime task patching', () => {
  it('does not let replayed history mutate the authoritative task status', () => {
    expect(shouldApplyRealtimeTaskPatch({ type: 'turn_started' }, 'replaying')).toBe(false)
    expect(shouldApplyRealtimeTaskPatch({ type: 'modeling_started', replayed: true }, 'connected')).toBe(false)
  })

  it('allows live task lifecycle events to update the visible task state', () => {
    expect(shouldApplyRealtimeTaskPatch({ type: 'turn_started' }, 'connected')).toBe(true)
    expect(shouldApplyRealtimeTaskPatch({ type: 'task_completed' }, 'running')).toBe(true)
    expect(shouldApplyRealtimeTaskPatch({ type: 'quota_exhausted' }, 'running')).toBe(true)
  })
})

describe('codex realtime replay state', () => {
  it('marks replayed completed sessions as snapshot history when events exist', () => {
    const state = createCodexRealtimeState()
    applyCodexRealtimeEvent(state, { type: 'assistant_snapshot', itemId: 'assistant-1', text: 'done', timestamp: 1 })
    applyCodexRealtimeEvent(state, { type: 'replay_done', running: false })

    expect(state.status).toBe('snapshot')
    expect(state.events).toHaveLength(1)
  })

  it('keeps active replay sessions running when the server reports a current turn', () => {
    const state = createCodexRealtimeState()
    applyCodexRealtimeEvent(state, { type: 'replay_done', running: true })

    expect(state.status).toBe('running')
  })
})
