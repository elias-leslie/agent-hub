import { describe, expect, it } from 'vitest'
import {
  attemptCost,
  attemptCostText,
  attemptDurationMs,
  attemptModels,
  attemptTokens,
  costTotalsParts,
  isModelSwitch,
  modelLabel,
  pauseExplanation,
} from '@/app/workflow-runs/utils'
import {
  attempt,
  CODEX,
  costTotals,
  OPUS_48,
  OPUS_55,
} from './workflow-runs-fixture'

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

describe('attemptTokens', () => {
  it('sums the reported parts when an executor gives no total, and is unknown without usage', () => {
    expect(
      attemptTokens(
        attempt({ usage: { input_tokens: 100, output_tokens: 20 } }),
      ),
    ).toBe(120)
    expect(attemptTokens(attempt({ usage: { total_tokens: 7 } }))).toBe(7)
    expect(attemptTokens(attempt({ usage: {} }))).toBeNull()
    expect(attemptTokens(attempt({ usage: null }))).toBeNull()
  })
})

describe('attempt cost and totals by basis', () => {
  it('labels an attempt cost with its basis and marks estimates', () => {
    const priced = attempt({
      usage: {
        cost_usd: 0.0123,
        cost_basis: 'metered',
        cost_source: 'provider_reported',
      },
    })
    expect(attemptCostText(priced)).toBe('$0.012 metered')
    const estimated = attempt({
      usage: {
        cost_usd: 0.03,
        cost_basis: 'subscription_equiv',
        cost_source: 'catalog_estimate',
      },
    })
    expect(attemptCostText(estimated)).toBe('$0.030 subscription equiv. (est.)')
  })

  it('reads attempts stored before bases were recorded, and never turns unknown into zero', () => {
    expect(attemptCost(attempt({ usage: { total_cost_usd: 0.5 } }))).toEqual({
      usd: 0.5,
      basis: 'subscription_equiv',
      source: 'provider_reported',
    })
    expect(attemptCost(attempt({ usage: { cost_usd: 0.2 } }))?.basis).toBe(
      'unknown',
    )
    expect(
      attemptCostText(
        attempt({
          usage: { input_tokens: 5, cost_usd: null, cost_basis: 'unknown' },
        }),
      ),
    ).toBe('cost n/a')
    expect(attemptCostText(attempt({ usage: null }))).toBe('cost n/a')
  })

  it('shows each basis on its own, with unpriced attempts counted apart', () => {
    expect(
      costTotalsParts(
        costTotals({ metered: 0.01, subscription_equiv: 0.5 }, 2),
      ),
    ).toEqual(['$0.010 metered', '$0.500 subscription equiv.', '2 unpriced'])
    expect(costTotalsParts(costTotals())).toEqual(['cost n/a'])
  })
})
