import { describe, expect, it } from 'vitest'
import { taskProgressPercent } from './progress'

describe('task progress percent', () => {
  it('shows 100 only for completed tasks', () => {
    expect(taskProgressPercent({ status: 'completed', progressPercent: 100 })).toBe(100)
    expect(taskProgressPercent({ status: 'running', progressPercent: 100 })).toBe(99)
    expect(taskProgressPercent({ status: 'paused_for_review', progressPercent: 100 })).toBe(99)
    expect(taskProgressPercent({ status: 'waiting_human', progressPercent: 100 })).toBe(99)
    expect(taskProgressPercent({ status: 'failed', progressPercent: 100 })).toBeNull()
    expect(taskProgressPercent({ status: 'cancelled', progressPercent: 100 })).toBeNull()
  })

  it('does not invent progress when no explicit backend percent exists', () => {
    expect(taskProgressPercent({ status: 'running' })).toBeNull()
    expect(taskProgressPercent({ status: 'running', isBootstrapping: true })).toBeNull()
    expect(taskProgressPercent({ status: 'paused_for_review' })).toBeNull()
    expect(taskProgressPercent({ status: 'waiting_human' })).toBeNull()
    expect(taskProgressPercent({
      status: 'running',
      steps: [
        { status: 'completed' },
        { status: 'running' },
      ],
    })).toBeNull()
  })

  it('keeps explicit partial progress for paused or waiting tasks', () => {
    expect(taskProgressPercent({ status: 'paused_for_review', progressPercent: 64 })).toBe(64)
    expect(taskProgressPercent({ status: 'waiting_human', progressPercent: 38 })).toBe(38)
  })

  it('keeps real partial progress for failed tasks without filling the bar', () => {
    expect(taskProgressPercent({ status: 'failed', progressPercent: 72 })).toBe(72)
    expect(taskProgressPercent({
      status: 'cancelled',
      steps: [
        { status: 'completed' },
        { status: 'failed' },
        { status: 'pending' },
      ],
    })).toBeNull()
  })
})
