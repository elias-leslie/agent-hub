import { describe, expect, it } from 'vitest'
import {
  buildLogEntries,
  parseEnvelope,
  splitScaffold,
} from '@/app/sessions/log/entries'
import { interleave } from '@/app/sessions/log/interleave'
import type { SessionListItem } from '@/lib/api/sessions'
import type { TimelineEvent } from '@/types/events'

let seq = 0
function ev(overrides: Partial<TimelineEvent>): TimelineEvent {
  seq += 1
  return {
    id: `e${seq}`,
    turn: 1,
    sequence: seq,
    event_type: 'assistant_message',
    role: null,
    content: null,
    tool_name: null,
    call_id: null,
    tool_input: null,
    tool_output: null,
    tokens: null,
    duration_ms: null,
    model_used: null,
    agent_id: null,
    agent_name: null,
    created_at: `2026-10-10T08:00:${String(seq % 60).padStart(2, '0')}Z`,
    ...overrides,
  }
}

describe('buildLogEntries: Codex', () => {
  it('shows a Bash call once with its exit code and hides the exec wrapper', () => {
    const entries = buildLogEntries([
      ev({
        event_type: 'tool_use',
        tool_name: 'exec',
        call_id: 'call_wrap',
        tool_input: {
          raw: 'text(await tools.exec_command({cmd:"rg -n foo app","workdir":"/srv"}));',
        },
      }),
      ev({
        event_type: 'tool_use',
        tool_name: 'Bash',
        call_id: 'exec-1',
        tool_input: {
          command: ['/bin/bash', '-lc', 'rg -n foo app'],
          wrapper_candidate_call_id: 'call_wrap',
        },
      }),
      ev({
        event_type: 'tool_result',
        call_id: 'exec-1',
        tool_output: { stdout: 'a:1\nb:2', exit_code: 0, status: 'completed' },
        duration_ms: 120,
      }),
      ev({
        event_type: 'tool_result',
        call_id: 'call_wrap',
        content: 'Script completed\nWall time 0.1 seconds',
      }),
    ])
    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({
      label: 'searched',
      summary: 'rg -n foo app',
      meta: 'exit 0 · 120ms · 2 lines',
      failed: false,
    })
  })

  it('hides an unreferenced wrapper whose command is already shown as Bash', () => {
    const entries = buildLogEntries([
      ev({
        event_type: 'tool_use',
        tool_name: 'exec',
        call_id: 'call_w2',
        tool_input: { raw: 'await tools.exec_command({cmd:"git status"})' },
      }),
      ev({
        event_type: 'tool_use',
        tool_name: 'Bash',
        call_id: 'exec-2',
        tool_input: { command: ['/bin/bash', '-lc', 'git status'] },
      }),
    ])
    expect(entries.map((entry) => entry.summary)).toEqual(['git status'])
  })

  it('renders apply_patch inside an exec wrapper as an edit with counts', () => {
    const patch =
      '*** Begin Patch\\n*** Update File: /srv/workspaces/projects/neri/app/x.py\\n@@\\n-old\\n+new\\n+more\\n*** End Patch'
    const [entry] = buildLogEntries([
      ev({
        event_type: 'tool_use',
        tool_name: 'exec',
        call_id: 'call_p',
        tool_input: {
          raw: `const patch = "${patch}";\ntext(await tools.apply_patch(patch));`,
        },
      }),
    ])
    expect(entry).toMatchObject({
      label: 'edited',
      summary: 'app/x.py',
      meta: '+2 −1',
    })
    expect(entry.detail?.type).toBe('diff')
  })

  it('marks failed commands and shows write_stdin polling as a muted line', () => {
    const entries = buildLogEntries([
      ev({
        event_type: 'tool_use',
        tool_name: 'Bash',
        call_id: 'exec-3',
        tool_input: { command: ['/bin/bash', '-lc', 'pytest -q'] },
      }),
      ev({
        event_type: 'tool_result',
        call_id: 'exec-3',
        tool_output: {
          stdout: '1 failed',
          exit_code: 1,
          status: 'failed',
          is_error: true,
        },
      }),
      ev({
        event_type: 'tool_use',
        tool_name: 'exec',
        call_id: 'call_poll',
        tool_input: { raw: 'tools.write_stdin({session_id:1,chars:""})' },
      }),
    ])
    expect(entries[0]).toMatchObject({
      label: 'ran',
      failed: true,
      meta: 'exit 1',
    })
    expect(entries[1]).toMatchObject({ kind: 'context', label: 'polled' })
  })

  it('reads inter-agent envelopes and approval reviews', () => {
    const entries = buildLogEntries([
      ev({
        event_type: 'user_message',
        content:
          'Message Type: NEW_TASK\nTask name: /root/storage_review\nSender: /root\nPayload:\nReview plan.md for blocking issues.',
      }),
      ev({
        event_type: 'user_message',
        content:
          'Message Type: MESSAGE\nTask name: /root\nSender: /root/storage_review\nPayload:\nDone, no blockers.',
      }),
      ev({
        event_type: 'assistant_message',
        content:
          '{"risk_level":"low","outcome":"allow","rationale":"Routine read."}',
      }),
    ])
    expect(entries.map((entry) => [entry.label, entry.summary])).toEqual([
      ['task', 'Review plan.md for blocking issues.'],
      ['message', 'storage_review: Done, no blockers.'],
      ['agent', 'approval allow · low risk · Routine read.'],
    ])
  })
})

describe('buildLogEntries: Claude Code', () => {
  it('reads output from the tool_use row and diffs edits', () => {
    const entries = buildLogEntries([
      ev({
        event_type: 'tool_use',
        tool_name: 'Bash',
        tool_input: { command: 'cd /srv/x && st check --quick' },
        tool_output: { result: JSON.stringify({ stdout: 'ok\n', stderr: '' }) },
      }),
      ev({
        event_type: 'tool_use',
        tool_name: 'Edit',
        tool_input: {
          file_path: '/srv/workspaces/projects/agent-hub/backend/app/x.py',
        },
        tool_output: {
          result: JSON.stringify({
            filePath: '/srv/workspaces/projects/agent-hub/backend/app/x.py',
            oldString: 'a\nb\nc',
            newString: 'a\nB\nB2\nc',
          }),
        },
      }),
    ])
    expect(entries[0]).toMatchObject({
      label: 'ran',
      summary: 'st check --quick',
    })
    expect(entries[0].detail).toMatchObject({ type: 'output', text: 'ok' })
    expect(entries[1]).toMatchObject({
      label: 'edited',
      summary: 'backend/app/x.py',
      meta: '+2 −1',
    })
  })

  it('pairs a separate tool_result by call_id and reads "Exit code" failures', () => {
    const entries = buildLogEntries([
      ev({
        event_type: 'tool_use',
        tool_name: 'Bash',
        call_id: 'toolu_1',
        tool_input: { command: 'ls /nope' },
      }),
      ev({
        event_type: 'tool_result',
        call_id: 'toolu_1',
        content: 'Exit code 2\nls: cannot access',
        tool_output: {
          content: 'Exit code 2\nls: cannot access',
          is_error: true,
        },
      }),
    ])
    expect(entries).toHaveLength(1)
    expect(entries[0]).toMatchObject({ failed: true, meta: 'exit 2' })
  })

  it('collapses harness scaffolding but keeps what the person wrote after it', () => {
    const entries = buildLogEntries([
      ev({
        event_type: 'user_message',
        content:
          '<pasted_content id="7f">big paste</pasted_content>\nread this and follow it',
      }),
      ev({
        event_type: 'user_message',
        content: '# AGENTS.md instructions for /srv\n\nlots of rules',
      }),
    ])
    expect(entries.map((entry) => [entry.kind, entry.summary])).toEqual([
      ['context', 'injected: pasted content'],
      ['prompt', 'read this and follow it'],
      ['context', 'injected: AGENTS.md'],
    ])
  })
})

describe('helpers', () => {
  it('splits nested leading tags', () => {
    expect(
      splitScaffold(
        '<environment_context>x</environment_context> <a b="c">y</a>hello',
      ),
    ).toEqual({
      names: ['environment context', 'a'],
      rest: 'hello',
    })
  })

  it('returns null for text that is not an envelope', () => {
    expect(parseEnvelope('hello')).toBeNull()
  })
})

function child(id: string, createdAt: string): SessionListItem {
  return {
    id,
    project_id: 'neri',
    provider: 'codex',
    model: 'gpt',
    status: 'completed',
    session_type: 'agent',
    created_at: createdAt,
    updated_at: createdAt,
  } as SessionListItem
}

describe('interleave', () => {
  const entries = buildLogEntries([
    ev({
      event_type: 'user_message',
      content: 'go',
      turn: 1,
      source_timestamp: '2026-10-10T08:00:00Z',
    }),
    ev({
      event_type: 'assistant_message',
      content: 'started',
      turn: 2,
      source_timestamp: '2026-10-10T09:00:00Z',
    }),
  ])

  it('batches consecutive children at their start time and adds turn separators', () => {
    const { items } = interleave(
      entries,
      [
        child('c1', '2026-10-10T08:10:00Z'),
        child('c2', '2026-10-10T08:20:00Z'),
        child('c3', '2026-10-10T10:00:00Z'),
      ],
      false,
    )
    expect(
      items.map((item) =>
        item.type === 'children'
          ? `children:${item.children.length}`
          : item.type,
      ),
    ).toEqual(['turn', 'entry', 'children:2', 'turn', 'entry', 'children:1'])
  })

  it('holds back children older than the loaded window while earlier history exists', () => {
    const { items, heldBack } = interleave(
      entries,
      [child('c0', '2026-10-10T07:00:00Z')],
      true,
    )
    expect(heldBack).toBe(1)
    expect(items.some((item) => item.type === 'children')).toBe(false)
  })
})

describe('context tidying', () => {
  const events = () => [
    ev({
      event_type: 'assistant_message',
      content: '## Safety Directive\n# Safety and autonomy',
    }),
    ev({
      event_type: 'assistant_message',
      content: '<skills_instructions>\n## Skills\n</skills_instructions>',
    }),
    ev({ event_type: 'user_message', content: 'Resume the triage' }),
    ev({ event_type: 'assistant_message', content: 'Starting now.' }),
  ]

  it('treats assistant messages before the first prompt as merged context when the log starts at the beginning', () => {
    const entries = buildLogEntries(events(), { fromStart: true })
    expect(entries.map((entry) => [entry.label, entry.summary])).toEqual([
      ['context', 'injected: Safety Directive, skills instructions'],
      ['you', 'Resume the triage'],
      ['agent', 'Starting now.'],
    ])
    expect(entries[0].raw).toHaveLength(2)
  })

  it('leaves agent messages alone when earlier history is not loaded', () => {
    const entries = buildLogEntries(events())
    expect(entries[0]).toMatchObject({ label: 'agent' })
  })
})
