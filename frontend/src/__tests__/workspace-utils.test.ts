import { describe, expect, it } from 'vitest'

import { prettifyDisplayText } from '@/app/persona/components/workspace-utils'

describe('workspace-utils prettifyDisplayText', () => {
  it('humanizes wrapped task payloads before display', () => {
    const wrappedPayload = `[{'type': 'text', 'text': "TASK:task-605a52fc|pending|P2|task|STANDARD\\nTITLE:Live validation: Persona dispatch judgment after workflow cleanup\\nDESCRIPTION:Temporary validation task to confirm the persona still reaches a clear readiness judgment after the latest workflow fixes.\\nOBJECTIVE:Use the persona on a temporary validation task and confirm the current task surfaces still lead to a clear dispatch judgment without extra friction."}]`

    const formatted = prettifyDisplayText(wrappedPayload)

    expect(formatted).toContain(
      'Task task-605a52fc · pending · P2 · task · STANDARD',
    )
    expect(formatted).toContain(
      'Title: Live validation: Persona dispatch judgment after workflow cleanup',
    )
    expect(formatted).toContain(
      'Description: Temporary validation task to confirm the persona still reaches a clear readiness judgment after the latest workflow fixes.',
    )
    expect(formatted).not.toContain("[{'type': 'text'")
  })
})
