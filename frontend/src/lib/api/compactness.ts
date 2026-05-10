import { fetchApi } from '@/lib/api-config'

export interface CompactnessPolicy {
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

export type CompactnessPolicyUpdate = Partial<CompactnessPolicy>

export async function fetchCompactnessPolicy(): Promise<CompactnessPolicy> {
  const res = await fetchApi('/api/compactness/policy')
  if (!res.ok) throw new Error('Failed to fetch compactness policy')
  return res.json()
}

export async function updateCompactnessPolicy(
  payload: CompactnessPolicyUpdate,
): Promise<CompactnessPolicy> {
  const res = await fetchApi('/api/compactness/policy', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error('Failed to save compactness policy')
  return res.json()
}
