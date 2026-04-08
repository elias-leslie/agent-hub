'use client'

import { NotesWorkspace } from '@summitflow/notes-ui'

export default function NotesPopoutPage() {
  return <NotesWorkspace apiPrefix="/api" projectScope="agent-hub" />
}
