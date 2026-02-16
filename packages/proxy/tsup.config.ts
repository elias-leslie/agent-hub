import { defineConfig } from 'tsup';

export default defineConfig({
    entry: ['src/index.ts', 'src/next.ts', 'src/express.ts'],
    format: ['cjs', 'esm'],
    dts: true,
    clean: true,
    external: ['http-proxy-middleware'],
});
