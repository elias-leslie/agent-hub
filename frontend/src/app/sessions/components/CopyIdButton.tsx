import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'

export function CopyIdButton({
  id,
  className,
  asSpan,
}: {
  id: string
  className?: string
  asSpan?: boolean
}) {
  const [copied, setCopied] = useState(false)

  const doCopy = async () => {
    await navigator.clipboard.writeText(id)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation()
    e.preventDefault()
    await doCopy()
  }

  const commonProps = {
    onClick: handleCopy,
    className: cn(
      'relative p-1 rounded-md transition-all cursor-pointer',
      'hover:bg-slate-700',
      'active:scale-95',
      className,
    ),
    title: copied ? undefined : 'Copy session ID',
  }

  const content = (
    <>
      {copied ? (
        <Check className="h-3.5 w-3.5 text-emerald-500" />
      ) : (
        <Copy className="h-3.5 w-3.5 text-slate-400 hover:text-slate-300" />
      )}
      {copied && (
        <span className="absolute -top-7 left-1/2 -translate-x-1/2 px-2 py-0.5 text-[10px] font-medium rounded bg-emerald-600 text-white whitespace-nowrap animate-in fade-in-0 zoom-in-95 duration-150">
          Copied!
        </span>
      )}
    </>
  )

  // Use span when inside another interactive element (button/link)
  if (asSpan) {
    return (
      <span
        role="button"
        tabIndex={0}
        {...commonProps}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.stopPropagation()
            e.preventDefault()
            doCopy()
          }
        }}
      >
        {content}
      </span>
    )
  }

  return <button {...commonProps}>{content}</button>
}
