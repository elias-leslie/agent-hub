import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Agent Hub Embed',
  robots: 'noindex',
}

/**
 * Minimal layout for embed mode — no AppShell, no sidebar, no header.
 * Just the bare children wrapped in a full-height container.
 */
export default function EmbedLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <div className="h-screen w-screen overflow-hidden bg-slate-950">
      {children}
    </div>
  )
}
