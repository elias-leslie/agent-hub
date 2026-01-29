import { useEffect } from "react";
import type { Message } from "../types";

export function useAutoScroll(
  messagesEndRef: React.RefObject<HTMLDivElement | null>,
  messages: Message[]
) {
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, messagesEndRef]);
}
