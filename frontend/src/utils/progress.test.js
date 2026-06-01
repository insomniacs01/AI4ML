import { describe, expect, it } from 'vitest'
import { taskProgressPercent } from './progress'

describe('task progress percent', () => {
  it('shows 100 only for completed tasks', () => {
    expect(taskProgressPercent({ status: 'completed', progressPercent: 100 })).toBe(100)
    expect(taskProgressPercent({ status: 'running', progressPercent: 100 })).toBe(99)
    expect(taskProgressPercent({ status: 'paused_for_review', progressPercent: 100 })).toBe(25)
    expect(taskProgressPercent({ status: 'waiting_human', progressPercent: 100 })).toBe(25)
    expect(taskProgressPercent({ status: 'failed', progressPercent: 100 })).toBe(0)
    expect(taskProgressPercent({ status: 'cancelled', progressPercent: 100 })).toBe(0)
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
    })).toBeGreaterThan(0)
    expect(taskProgressPercent({
      status: 'cancelled',
      steps: [
        { status: 'completed' },
        { status: 'failed' },
        { status: 'pending' },
      ],
    })).toBeLessThan(100)
  })
})
