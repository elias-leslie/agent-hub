import { describe, expect, it } from 'vitest'
import {
  attemptDurationMs,
  attemptModels,
  isModelSwitch,
  modelLabel,
  pauseExplanation,
} from '@/app/workflow-runs/utils'
import { attempt, CODEX, OPUS_48, OPUS_55 } from './workflow-runs-fixture'

describe('workflow run model labels', () => {
  it('reads Claude ids as family and version, and leaves other ids alone', () => {
    expect(modelLabel(OPUS_55)).toBe('Opus 5.5')
    expect(modelLabel('claude-opus-4-8-20260115')).toBe('Opus 4.8')
    expect(modelLabel(CODEX)).toBe(CODEX)
    expect(modelLabel(null)).toBe('unknown model')
  })

  it('does not count a provider prefix or dated snapshot as a different model', () => {
    expect(
      isModelSwitch('anthropic/claude-opus-5-5', 'claude-opus-5-5-20260401'),
    ).toBe(false)
    expect(isModelSwitch(OPUS_55, OPUS_48)).toBe(true)
    expect(isModelSwitch(OPUS_55, null)).toBe(false)
  })
})

describe('attemptModels', () => {
  it('flags an answer from a different model than the one asked', () => {
    const models = attemptModels(
      attempt({ served_models: [OPUS_48], served_model: OPUS_48 }),
    )
    expect(models).toEqual({
      asked: OPUS_55,
      answered: OPUS_48,
      substituted: true,
    })
  })

  it('flags a provider-reported substitution even without a served model', () => {
    const models = attemptModels(
      attempt({
        served_models: [],
        served_model: null,
        outcome: { kind: 'substituted', requested_model: OPUS_55 },
      }),
    )
    expect(models.substituted).toBe(true)
  })

  it('has no answering model for a refused, limited or failed attempt', () => {
    const refused = attempt({
      status: 'failed',
      outcome: { kind: 'refused', requested_model: OPUS_55, category: 'cyber' },
    })
    expect(attemptModels(refused)).toEqual({
      asked: OPUS_55,
      answered: null,
      substituted: false,
    })
    expect(
      attemptModels(attempt({ status: 'active', served_models: [] })).answered,
    ).toBeNull()
  })

  it('treats the same model as plain', () => {
    expect(attemptModels(attempt()).substituted).toBe(false)
  })
})

describe('attempt timing and pause copy', () => {
  it('has no duration until the attempt has finished', () => {
    expect(attemptDurationMs(attempt())).toBe(42_000)
    expect(attemptDurationMs(attempt({ finished_at: null }))).toBeNull()
  })

  it('says what a usage-limit pause is waiting for', () => {
    const text = pauseExplanation(
      { reason: 'usage_limit_wait', resume_after: 1_800_000_000 },
      'plan',
    )
    expect(text).toContain('Step "plan" is waiting for a usage limit to reset')
    expect(text).toContain('resumes by itself')
  })
})
