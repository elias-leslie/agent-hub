import { useEffect } from "react";
import type { ApprovalDecision } from "./types";

interface UseKeyboardShortcutsOptions {
  onDecision: (decision: ApprovalDecision, rememberChoice: boolean) => void;
  rememberChoice: boolean;
  onClose?: () => void;
}

export function useKeyboardShortcuts({
  onDecision,
  rememberChoice,
  onClose,
}: UseKeyboardShortcutsOptions) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;

      switch (e.key.toLowerCase()) {
        case "y":
        case "enter":
          e.preventDefault();
          onDecision("approve", rememberChoice);
          break;
        case "a":
          if (e.shiftKey) {
            e.preventDefault();
            onDecision("approve_all", false);
          }
          break;
        case "n":
          e.preventDefault();
          onDecision("deny", rememberChoice);
          break;
        case "d":
          if (e.shiftKey) {
            e.preventDefault();
            onDecision("deny_all", false);
          }
          break;
        case "escape":
          onClose?.();
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onDecision, rememberChoice, onClose]);
}
