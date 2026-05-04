import { describe, expect, it } from 'vitest'

import { analyzeCompactness } from '@/lib/compactness'

describe('analyzeCompactness', () => {
  it('flags large filler-heavy prompts', () => {
    const report = analyzeCompactness(
      `Please keep this prompt really clear.\n${'Example: keep signal.\n'.repeat(90)}`,
      'prompt',
    )

    expect(report.tokens).toBeGreaterThan(350)
    expect(
      report.warnings.some((warning) => warning.includes('large prompt')),
    ).toBe(true)
    expect(
      report.warnings.some((warning) => warning.includes('long prompt')),
    ).toBe(true)
    expect(
      report.errors.some((error) => error.includes('filler terms found')),
    ).toBe(true)
    expect(
      report.errors.some((error) => error.includes('example markers found')),
    ).toBe(true)
  })

  it('flags long multi-line memories', () => {
    const report = analyzeCompactness(
      [
        '**Prompt Hygiene**: Keep prompts compact and focused.',
        'Use one canonical prompt.',
        'Drop overlap.',
        'Drop filler.',
        'Split extra rules.',
      ].join('\n'),
      'memory',
    )

    expect(
      report.warnings.some((warning) => warning.includes('multi-line memory')),
    ).toBe(true)
  })

  it('leaves lean content warning-free', () => {
    const report = analyzeCompactness(
      '**Quality Checks**: Use st check for repo checks.',
      'memory',
    )

    expect(report.warnings).toEqual([])
    expect(report.errors).toEqual([])
  })

  it('flags offer-back phrasing', () => {
    const report = analyzeCompactness(
      'Answer exact. If you want more, ask for details.',
      'prompt',
    )

    expect(
      report.errors.some((error) =>
        error.includes('offer-back phrasing found'),
      ),
    ).toBe(true)
  })
})
