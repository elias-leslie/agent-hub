"""No model requests: verify public-plugin delivery and native CLI launch semantics."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_launcher_resolves_native_install_and_keeps_authenticated_service(tmp_path):
    binary = tmp_path / '.opencode/bin/opencode'
    binary.parent.mkdir(parents=True)
    log = tmp_path / 'argv.jsonl'
    binary.write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
with open(os.environ['ARGV_LOG'],'a') as out: out.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1:3] == ['api','session.create']:
 print(json.dumps({'data':{'id':'ses_native_allocated','model':{'providerID':'opencode','id':'deepseek-v4.1-flash-free'},'location':{'directory':os.getcwd()}}}))
if sys.argv[1:3] == ['session','export']:
 print(json.dumps({'info':{'id':sys.argv[3]},'messages':[]}))
''')
    binary.chmod(0o700)
    client = tmp_path / '.local/bin/agent-hub-context-client'
    client.parent.mkdir(parents=True)
    client.write_text('#!/usr/bin/env python3\nimport sys\nsys.stdin.read()\n')
    client.chmod(0o700)
    launcher = ROOT / 'integrations/context-delivery/opencode/launcher'
    result = subprocess.run([str(launcher), 'run', '--model', 'opencode/deepseek-v4.1-flash-free', 'hello'],
        env={**os.environ, 'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin', 'ARGV_LOG': str(log)}, capture_output=True)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert calls[0][:2] == ['api', 'session.create']
    assert json.loads(calls[0][-1])['permissions'] == [{'action': '*', 'resource': '*', 'effect': 'allow'}]
    assert calls[1][:3] == ['run', '--session', 'ses_native_allocated']
    assert '--standalone' not in calls[1]
    assert calls[1][-1] == 'hello'
    assert calls[2][:2] == ['session', 'export']


@pytest.mark.parametrize("degraded", [False, True])
def test_public_plugin_appends_context_and_syncs_after_native_idle(tmp_path, degraded):
    # OpenCode supplies @opencode/plugin; this test replaces only its identity helper.
    source = (ROOT / 'integrations/context-delivery/opencode/agent-hub.js').read_text()
    source = source.replace("import { Plugin } from '@opencode/plugin'", 'const Plugin = { define: (value) => value }')
    plugin = tmp_path / 'adapter.mjs'
    plugin.write_text(source)
    client = tmp_path / '.local/bin/agent-hub-context-client'
    client.parent.mkdir(parents=True)
    client.write_text('''#!/usr/bin/env python3
import json,os,sys
if sys.argv[1] == 'deliver': print(json.dumps({'status':os.environ.get('DELIVERY_STATUS','ok'),'rendered':'canonical context'}))
else: sys.stdin.read()
''')
    client.chmod(0o700)
    runner = tmp_path / 'test.mjs'
    runner.write_text('''import assert from 'node:assert/strict';
import plugin from './adapter.mjs';
let hook, idle;
const waiting = new Promise(resolve => { idle = resolve });
const cleanup = await plugin.setup({session: {
 hook: async (name, callback) => { assert.equal(name, 'context'); hook = callback; return {dispose: async () => {}} },
 get: async () => ({location: {directory: '/fixture'}}), context: async () => [], wait: () => waiting,
}});
const event = {sessionID: 'ses_test', model: {providerID: 'opencode', id: 'glm-5.3-flash-free'}, tools: {}, system: [{type:'text',text:'native'}]};
await hook(event);
assert.deepEqual(event.system.map(p => p.text), process.env.DELIVERY_STATUS === 'ok' ? ['native', 'canonical context'] : ['native']);
idle(); await cleanup();
''')
    result = subprocess.run(['node', str(runner)], env={**os.environ, 'HOME': str(tmp_path), 'DELIVERY_STATUS': 'degraded' if degraded else 'ok'}, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr

    assert ('supplemental context unavailable' in result.stderr.decode()) is degraded
