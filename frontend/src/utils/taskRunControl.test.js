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

  it('does not approve a pending plan approval step when the run is interrupted', () => {
    const options = continueRunOptions(
      { status: 'paused_for_review', codex_status: 'interrupted' },
      {
        progress: {
          status: 'interrupted',
          steps: [
            { id: 'dataset_analysis', status: 'interrupted' },
            { id: 'awaiting_plan_approval', status: 'pending' },
          ],
        },
      },
      { planText: '# placeholder' },
    )

    expect(options).toEqual({
      resume_after_human: false,
      resume_interrupted: true,
      plan_text: null,
    })
  })

  it('uses plan approval only when the plan step is waiting for human input', () => {
    const options = continueRunOptions(
      { status: 'paused_for_review', codex_status: 'running' },
      {
        progress: {
          status: 'running',
          steps: [
            { id: 'plan_ready', status: 'waiting_human' },
          ],
        },
      },
      { planText: '# generated plan' },
    )

    expect(options).toEqual({
      resume_after_human: true,
      resume_interrupted: false,
      plan_text: '# generated plan',
    })
  })
})
