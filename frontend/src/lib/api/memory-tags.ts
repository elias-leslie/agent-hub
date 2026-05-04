import { fetchApi } from '@/lib/api-config'

export async function bulkTag(
  uuids: string[],
  addTags?: string[],
  removeTags?: string[],
): Promise<{ updated: number; failed: number }> {
  const res = await fetchApi('/api/memory/episodes/bulk-tag', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      uuids,
      add_tags: addTags || [],
      remove_tags: removeTags || [],
    }),
  })
  if (!res.ok) throw new Error('Failed to bulk tag episodes')
  return res.json()
}
