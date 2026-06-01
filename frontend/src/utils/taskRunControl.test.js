import { describe, expect, it } from 'vitest'
import { continueRunOptions } from '@/utils/taskRunControl'

describe('continueRunOptions', () => {
  it('approves a generated plan when a paused task is waiting for plan approval', () => {
    const options = continueRunOptions(
      { status: 'paused_for_review', codex_status: 'waiting_plan_approval' },
      { progress: { status: 'waiting_plan_approval' } },
      { planText: '# plan' },
    )

    expect(options).toEqual({
      resume_after_human: true,
      resume_interrupted: false,
      plan_text: '# plan',
    })
  })

  it('uses interrupted resume only for interrupted paused workspaces', () => {
    const options = continueRunOptions(
      { status: 'paused_for_review', codex_status: 'interrupted' },
      { progress: { status: 'interrupted' } },
    )

    expect(options).toEqual({
      resume_after_human: false,
      resume_interrupted: true,
      plan_text: null,
    })
  })
})
