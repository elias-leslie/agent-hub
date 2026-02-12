import { useState, useEffect } from "react";
import type { ApprovalDecision } from "./types";

interface UseApprovalTimerOptions {
  timeoutSeconds: number;
  onTimeout: (decision: ApprovalDecision) => void;
}

export function useApprovalTimer({
  timeoutSeconds,
  onTimeout,
}: UseApprovalTimerOptions) {
  const [timeRemaining, setTimeRemaining] = useState(timeoutSeconds);

  useEffect(() => {
    if (timeRemaining <= 0) {
      onTimeout("timeout");
      return;
    }

    const timer = setInterval(() => {
      setTimeRemaining((prev) => prev - 1);
    }, 1000);

    return () => clearInterval(timer);
  }, [timeRemaining, onTimeout]);

  const timeoutPercentage = (timeRemaining / timeoutSeconds) * 100;
  const isUrgent = timeRemaining <= 10;

  return { timeRemaining, timeoutPercentage, isUrgent };
}
