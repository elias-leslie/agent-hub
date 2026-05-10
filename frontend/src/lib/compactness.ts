export type CompactnessKind = 'prompt' | 'memory'

export interface CompactnessReport {
  kind: CompactnessKind
  chars: number
  lines: number
  tokens: number
  errors: string[]
  warnings: string[]
}

export interface CompactnessThresholds {
  memory_max_chars: number
  memory_max_lines: number
  prompt_max_tokens: number
  prompt_max_lines: number
  max_sentence_words: number
  max_avg_sentence_words: number
  avg_sentence_min_words: number
  max_article_ratio_permille: number
  article_ratio_min_words: number
}

export const COMPACTNESS_DEFAULTS: CompactnessThresholds = {
  memory_max_chars: 280,
  memory_max_lines: 4,
  prompt_max_tokens: 350,
  prompt_max_lines: 80,
  max_sentence_words: 24,
  max_avg_sentence_words: 16,
  avg_sentence_min_words: 120,
  max_article_ratio_permille: 85,
  article_ratio_min_words: 80,
}

const FILLER_PATTERNS: Array<[string, RegExp]> = [
  ['just', /\bjust\b/i],
  ['really', /\breally\b/i],
  ['basically', /\bbasically\b/i],
  ['please', /\bplease\b/i],
  ['let me know', /\blet me know\b/i],
  ['feel free', /\bfeel free\b/i],
  ['i recommend', /\bi recommend\b/i],
  ['i suggest', /\bi suggest\b/i],
  ['you should', /\byou should\b/i],
  ['make sure', /\bmake sure\b/i],
]
const EXAMPLE_PATTERN = /\bfor example\b|\be\.g\.\b|example:/gi
const HEDGE_PATTERN =
  /\b(?:maybe|probably|likely|might|could|should|usually|generally|try to)\b/i
const SOFT_TONE_PATTERN =
  /\b(?:be thorough|be objective|be specific|be precise|be natural|be conversational|be helpful|be friendly|be confident)\b/i
const OFFER_BACK_PATTERN =
  /\b(?:if you want|would you like|happy to help|happy to|let me know if)\b/i
const PROSE_CODE_BLOCK_PATTERN = /```[\s\S]*?```/g
const INLINE_CODE_PATTERN = /`[^`]*`/g
const PLACEHOLDER_PATTERN = /\{[^{}\n]+\}/g
const WORD_PATTERN = /[A-Za-z']+/g
const ARTICLE_WORDS = new Set(['a', 'an', 'the'])

function lineCount(content: string): number {
  return content ? content.split('\n').length : 0
}

function estimateTokens(content: string): number {
  return content ? Math.ceil(content.length / 4) : 0
}

function detectFillers(content: string): string[] {
  return FILLER_PATTERNS.filter(([, pattern]) => pattern.test(content)).map(
    ([label]) => label,
  )
}

function stripNonProse(content: string): string {
  return content
    .replace(PROSE_CODE_BLOCK_PATTERN, ' ')
    .replace(INLINE_CODE_PATTERN, ' ')
    .replace(PLACEHOLDER_PATTERN, ' ')
    .replace(/^\s{0,3}#+\s*/gm, '')
    .replace(/^\s*[-*]\s+/gm, '')
    .replace(/^\s*\d+\.\s+/gm, '')
}

function proseWords(content: string): string[] {
  return stripNonProse(content).toLowerCase().match(WORD_PATTERN) ?? []
}

function extractSentences(content: string): string[] {
  return stripNonProse(content)
    .split(/(?<=[.!?])\s+|\n+/)
    .map((value) => value.trim())
    .filter((value) => WORD_PATTERN.test(value))
}

export function analyzeCompactness(
  content: string,
  kind: CompactnessKind,
  policy: CompactnessThresholds = COMPACTNESS_DEFAULTS,
): CompactnessReport {
  const chars = content.length
  const lines = lineCount(content)
  const tokens = estimateTokens(content)
  const errors: string[] = []
  const warnings: string[] = []
  const fillerHits = detectFillers(content)
  const words = proseWords(content)
  const sentences = extractSentences(content)

  if (kind === 'prompt') {
    if (tokens > policy.prompt_max_tokens) {
      warnings.push(
        `large prompt (${tokens} tok). Hot-path prompts pay this every turn.`,
      )
    }
    if (lines > policy.prompt_max_lines) {
      warnings.push(
        `long prompt (${lines} lines). Collapse repeated examples and overlap.`,
      )
    }
  } else {
    if (chars > policy.memory_max_chars) {
      warnings.push(
        `long memory (${chars} chars). Keep one atomic rule; split if needed.`,
      )
    }
    if (lines > policy.memory_max_lines) {
      warnings.push(
        `multi-line memory (${lines} lines). Prefer one short rule body.`,
      )
    }
  }

  if (fillerHits.length > 0) {
    errors.push(`filler terms found: ${fillerHits.slice(0, 4).join(', ')}`)
  }

  if (EXAMPLE_PATTERN.test(content)) {
    errors.push(
      'example markers found. Strip examples; keep direct rules only.',
    )
  }

  if (HEDGE_PATTERN.test(content)) {
    errors.push(
      'hedging found. Replace maybe/should/could-style phrasing with direct rules.',
    )
  }

  if (SOFT_TONE_PATTERN.test(content)) {
    errors.push(
      "soft-tone phrasing found. Replace 'be X' guidance with direct action rules.",
    )
  }

  if (OFFER_BACK_PATTERN.test(content)) {
    errors.push(
      'offer-back phrasing found. Remove optional follow-up or helper language.',
    )
  }

  if (words.length >= policy.article_ratio_min_words) {
    const articleRatio =
      words.filter((word) => ARTICLE_WORDS.has(word)).length / words.length
    if (articleRatio > policy.max_article_ratio_permille / 1000) {
      errors.push(
        `article-heavy prose (${(articleRatio * 100).toFixed(1)}%). Drop articles and compress sentence shape.`,
      )
    }
  }

  const sentenceLengths = sentences.map(
    (sentence) => sentence.match(WORD_PATTERN)?.length ?? 0,
  )
  if (sentenceLengths.some((count) => count > policy.max_sentence_words)) {
    errors.push(
      'long prose sentences found. Split into short direct lines or bullets.',
    )
  }

  if (
    words.length >= policy.avg_sentence_min_words &&
    sentenceLengths.length > 0
  ) {
    const averageSentenceWords =
      sentenceLengths.reduce((sum, count) => sum + count, 0) /
      sentenceLengths.length
    if (averageSentenceWords > policy.max_avg_sentence_words) {
      errors.push(
        `average sentence too long (${averageSentenceWords.toFixed(1)} words). Compress prose.`,
      )
    }
  }

  return { kind, chars, lines, tokens, errors, warnings }
}
