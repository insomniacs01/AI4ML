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

  it('keeps only the latest realtime events and cached item state', () => {
    const state = createCodexRealtimeState()

    for (let index = 0; index < 300; index += 1) {
      applyCodexRealtimeEvent(state, {
        type: 'tool_start',
        toolUseId: `tool-${index}`,
        command: `python train_${index}.py`,
        timestamp: index,
      })
    }

    expect(state.events).toHaveLength(240)
    expect(state.events[0].id).toContain('tool-60')
    expect(state.toolItems.size).toBeLessThanOrEqual(120)
  })

  it('truncates large tool output before storing it in realtime state', () => {
    const state = createCodexRealtimeState()
    const output = 'x'.repeat(12000)

    applyCodexRealtimeEvent(state, {
      type: 'tool_result',
      toolUseId: 'tool-large-output',
      stdout: output,
      timestamp: 1,
    })

    expect(state.events[0].stdout).toHaveLength(4000)
    expect(state.toolItems.get('tool-large-output').stdout).toHaveLength(4000)
  })
})
