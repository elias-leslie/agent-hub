import { useState } from "react";
import type { MemoryEpisode, MemoryCategory } from "@/lib/memory-api";
import { addEpisode, deleteMemory, updateEpisodeProperties } from "@/lib/memory-api";

interface UseEpisodeEditorProps {
  episode: MemoryEpisode;
  onSaved: () => void;
  onClose: () => void;
}

export function useEpisodeEditor({ episode, onSaved, onClose }: UseEpisodeEditorProps) {
  const [content, setContent] = useState(episode.content);
  const [tier, setTier] = useState<MemoryCategory>(episode.category);
  const [pinned, setPinned] = useState(episode.pinned ?? false);
  const [summary, setSummary] = useState(episode.summary ?? "");
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasChanges =
    content !== episode.content ||
    tier !== episode.category ||
    pinned !== (episode.pinned ?? false) ||
    summary !== (episode.summary ?? "");

  async function handleSave() {
    if (!hasChanges) {
      onClose();
      return;
    }

    setIsSaving(true);
    setError(null);

    try {
      const contentOrTierChanged = content !== episode.content || tier !== episode.category;
      const pinnedChanged = pinned !== (episode.pinned ?? false);
      const summaryChanged = summary !== (episode.summary ?? "");

      let newUuid = episode.uuid;

      // If content or tier changed, need delete+create flow
      if (contentOrTierChanged) {
        // Step 1: Create new episode with preserved stats
        const newEpisode = await addEpisode({
          content,
          source: episode.source,
          source_description: episode.source_description,
          injection_tier: tier,
          preserve_stats_from: episode.uuid,
        });
        newUuid = newEpisode.uuid;

        // Step 2: Delete original episode
        await deleteMemory(episode.uuid);
      }

      // Update properties on the (possibly new) episode
      const propsToUpdate: { pinned?: boolean; summary?: string } = {};
      if (pinnedChanged || (contentOrTierChanged && pinned)) {
        propsToUpdate.pinned = pinned;
      }
      if (summaryChanged || (contentOrTierChanged && summary)) {
        propsToUpdate.summary = summary;
      }
      if (Object.keys(propsToUpdate).length > 0) {
        await updateEpisodeProperties(newUuid, propsToUpdate);
      }

      // Success - close modal and trigger refresh
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save changes");
    } finally {
      setIsSaving(false);
    }
  }

  return {
    content,
    setContent,
    tier,
    setTier,
    pinned,
    setPinned,
    summary,
    setSummary,
    isSaving,
    error,
    hasChanges,
    handleSave,
  };
}
