import { Cpu, Server } from 'lucide-react'

export { formatTokens } from '@/lib/formatters'

export function formatDate(dateString: string): string {
  const date = new Date(dateString)
  return date.toLocaleString()
}

export function getProviderIcon(provider: string) {
  if (provider === 'claude') {
    return <Cpu className="h-5 w-5 text-orange-500" />
  }
  return <Server className="h-5 w-5 text-amber-500" />
}
