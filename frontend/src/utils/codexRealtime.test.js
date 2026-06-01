import { describe, expect, it } from 'vitest'
import { shouldApplyRealtimeTaskPatch } from './codexRealtime'

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
