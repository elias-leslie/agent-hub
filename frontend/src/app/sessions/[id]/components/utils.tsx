import { Cpu, Server } from "lucide-react";

export function formatDate(dateString: string): string {
  const date = new Date(dateString);
  return date.toLocaleString();
}

export function formatTokens(tokens: number): string {
  if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(1)}M`;
  if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
  return tokens.toString();
}

export function getProviderIcon(provider: string) {
  if (provider === "claude") {
    return <Cpu className="h-5 w-5 text-orange-500" />;
  }
  return <Server className="h-5 w-5 text-blue-500" />;
}
