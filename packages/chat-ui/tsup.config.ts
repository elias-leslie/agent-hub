import { defineConfig } from 'tsup';

export default defineConfig({
    // `voice` is its own entry so the main one never loads @agent-hub/passport-client.
    entry: ['src/index.ts', 'src/voice.ts'],
    format: ['cjs', 'esm'],
    dts: true,
    clean: true,
    banner: {
        js: '"use client";',
    },
});
