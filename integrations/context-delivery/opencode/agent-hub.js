// OpenCode v2 public plugin API. Native authentication and inference stay in OpenCode.
import { Plugin } from '@opencode/plugin'
import { spawn } from 'node:child_process'
import { homedir } from 'node:os'
import { join } from 'node:path'

function client(args, input) {
  return new Promise((resolve, reject) => {
    const child = spawn(join(homedir(), '.local/bin/agent-hub-context-client'), args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      timeout: 20000,
    })
    let stdout = ''
    child.stdout.on('data', (chunk) => { stdout += chunk })
    // Never echo transport errors, credentials or delivered context to the terminal.
    child.stderr.resume()
    child.on('error', reject)
    child.on('close', (code) => code === 0 ? resolve(stdout) : reject(new Error('Agent Hub unavailable')))
    child.stdin.end(input ? JSON.stringify(input) : undefined)
  })
}

export default Plugin.define({
  id: 'agent-hub.context',
  async setup(ctx) {
    const pending = new Map()
    const sync = async (sessionID, phase) => {
      const info = await ctx.session.get({ sessionID })
      const messages = await ctx.session.context({ sessionID })
      await client(['sync-opencode', '--surface', 'opencode'], { info, messages, phase })
    }
    const registration = await ctx.session.hook('context', async (event) => {
      try {
        const info = await ctx.session.get({ sessionID: event.sessionID })
        const args = ['deliver', '--surface', 'opencode', '--emit', 'json',
          '--session', event.sessionID, '--cwd', info.location.directory,
          '--provider', event.model.providerID, '--model', event.model.id]
        // Only declare shell access when OpenCode actually supplied its shell tool.
        if (Object.hasOwn(event.tools, 'shell')) args.push('--capability', 'shell')
        const contract = JSON.parse(await client(args))
        if (contract.status !== 'ok' || typeof contract.rendered !== 'string') throw new Error('invalid delivery')
        event.system.push({ type: 'text', text: contract.rendered })
      } catch {
        process.stderr.write('Agent Hub supplemental context unavailable; OpenCode continues with native context.\n')
      }
      // wait() observes this native turn becoming idle, including tool continuations.
      // One waiter per session avoids duplicate exports while a tool loop is active.
      if (!pending.has(event.sessionID)) {
        const job = ctx.session.wait({ sessionID: event.sessionID })
          .then(() => sync(event.sessionID, 'idle'))
          .catch(() => process.stderr.write('OpenCode session sync unavailable.\n'))
          .finally(() => pending.delete(event.sessionID))
        pending.set(event.sessionID, job)
      }
    })
    return async () => {
      await registration.dispose()
      await Promise.allSettled(pending.values())
    }
  },
})
