// Bundle src/extension.js into dist/extension.js, the file package.json's "main" names.
// `node esbuild.mjs` builds once; `node esbuild.mjs --watch` rebuilds on every change.
import { build, context } from 'esbuild';

const options = {
  entryPoints: ['src/extension.js'],
  outfile: 'dist/extension.js',
  bundle: true,
  platform: 'node',
  format: 'cjs',
  target: 'node18',
  external: ['vscode'],
  sourcemap: true,
  logLevel: 'info',
};

if (process.argv.includes('--watch')) {
  const ctx = await context(options);
  await ctx.watch();
} else {
  await build(options);
}
