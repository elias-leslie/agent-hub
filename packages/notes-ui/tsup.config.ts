import { defineConfig } from 'tsup';

export default defineConfig({
    entry: ['src/index.ts'],
    format: ['cjs', 'esm'],
    dts: true,
    clean: true,
    banner: context => ({
        js: context.entry === 'src/index.ts' ? '"use client";' : '',
    }),
});
