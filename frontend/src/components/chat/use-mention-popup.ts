import { useState, useMemo, useCallback, useEffect } from "react";
import type { ModelOption } from "./model-options";
import { MODEL_OPTIONS } from "./model-options";

export function useMentionPopup(input: string, selectedModels: ModelOption[]) {
  const [showMentionPopup, setShowMentionPopup] = useState(false);
  const [mentionFilter, setMentionFilter] = useState("");
  const [mentionSelectedIndex, setMentionSelectedIndex] = useState(0);

  const filteredModels = useMemo(() => {
    const selectedAliases = new Set(selectedModels.map((m) => m.alias));
    const available = MODEL_OPTIONS.filter((m) => !selectedAliases.has(m.alias));
    if (!mentionFilter) return available;
    const lowerFilter = mentionFilter.toLowerCase();
    return available.filter(
      (m) =>
        m.alias.toLowerCase().includes(lowerFilter) ||
        m.hint.toLowerCase().includes(lowerFilter)
    );
  }, [mentionFilter, selectedModels]);

  useEffect(() => {
    setMentionSelectedIndex(0);
  }, [filteredModels]);

  const triggerMentionPopup = useCallback(() => {
    setShowMentionPopup(true);
    setMentionFilter("");
    setMentionSelectedIndex(0);
  }, []);

  const closeMentionPopup = useCallback(() => {
    setShowMentionPopup(false);
    setMentionFilter("");
  }, []);

  const updateMentionFilter = useCallback((value: string) => {
    const atMatch = value.match(/@(\w*)$/);
    if (atMatch) {
      setShowMentionPopup(true);
      setMentionFilter(atMatch[1]);
    } else if (showMentionPopup && !value.includes("@")) {
      setShowMentionPopup(false);
      setMentionFilter("");
    }
  }, [showMentionPopup]);

  const handleMentionNavigation = useCallback((key: string): boolean => {
    if (!showMentionPopup) return false;

    switch (key) {
      case "ArrowDown":
        setMentionSelectedIndex((prev) =>
          prev < filteredModels.length - 1 ? prev + 1 : 0
        );
        return true;
      case "ArrowUp":
        setMentionSelectedIndex((prev) =>
          prev > 0 ? prev - 1 : filteredModels.length - 1
        );
        return true;
      case "Escape":
        closeMentionPopup();
        return true;
      default:
        return false;
    }
  }, [showMentionPopup, filteredModels.length, closeMentionPopup]);

  return {
    showMentionPopup,
    mentionFilter,
    mentionSelectedIndex,
    filteredModels,
    triggerMentionPopup,
    closeMentionPopup,
    updateMentionFilter,
    handleMentionNavigation,
  };
}
