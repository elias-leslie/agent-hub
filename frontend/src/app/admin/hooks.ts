import { useState, useCallback, useEffect, useRef } from "react";

export function useHoldToConfirm(onConfirm: () => void, holdDuration: number = 1000) {
  const [isHolding, setIsHolding] = useState(false);
  const [progress, setProgress] = useState(0);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const startTimeRef = useRef<number>(0);

  const start = useCallback(() => {
    setIsHolding(true);
    startTimeRef.current = Date.now();
    intervalRef.current = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current;
      const newProgress = Math.min((elapsed / holdDuration) * 100, 100);
      setProgress(newProgress);
      if (newProgress >= 100) {
        if (intervalRef.current) clearInterval(intervalRef.current);
        onConfirm();
        setIsHolding(false);
        setProgress(0);
      }
    }, 16);
  }, [holdDuration, onConfirm]);

  const cancel = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    setIsHolding(false);
    setProgress(0);
  }, []);

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  return { isHolding, progress, start, cancel };
}
