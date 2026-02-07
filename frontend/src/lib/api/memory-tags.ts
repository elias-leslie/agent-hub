import { fetchApi } from "@/lib/api-config";

export async function getEpisodeTags(uuid: string): Promise<string[]> {
  const res = await fetchApi(`/api/memory/episodes/${uuid}/tags`);
  if (!res.ok) throw new Error("Failed to fetch episode tags");
  const data = await res.json();
  return data.tags;
}

export async function setEpisodeTags(
  uuid: string,
  tags: string[]
): Promise<void> {
  const res = await fetchApi(`/api/memory/episodes/${uuid}/tags`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tags }),
  });
  if (!res.ok) throw new Error("Failed to set episode tags");
}

export async function bulkTag(
  uuids: string[],
  addTags?: string[],
  removeTags?: string[]
): Promise<{ updated: number; failed: number }> {
  const res = await fetchApi("/api/memory/episodes/bulk-tag", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      uuids,
      add_tags: addTags || [],
      remove_tags: removeTags || [],
    }),
  });
  if (!res.ok) throw new Error("Failed to bulk tag episodes");
  return res.json();
}

export async function getAllTags(): Promise<string[]> {
  const res = await fetchApi("/api/memory/tags");
  if (!res.ok) throw new Error("Failed to fetch tags");
  const data = await res.json();
  return data.tags;
}
