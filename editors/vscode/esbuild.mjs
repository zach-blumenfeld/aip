// Two bundles. dist/extension.js, the file package.json's "main" names: src/extension.js for node,
// `vscode` left external. dist/preview.js and dist/preview.css, what the graph preview's webview
// loads: src/webview/main.tsx with the console's step graph (../../console/src/graph and
// ../../console/src/views/StepGraph.tsx), React included. `node esbuild.mjs` builds once;
// `node esbuild.mjs --watch` rebuilds on every change.
import { build, context } from 'esbuild';
import { oneReact } from './one-react.mjs';

const extension = {
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

const preview = {
  entryPoints: ['src/webview/main.tsx'],
  outfile: 'dist/preview.js',
  bundle: true,
  platform: 'browser',
  format: 'iife',
  target: 'es2022',
  jsx: 'automatic',
  minify: true,
  define: { 'process.env.NODE_ENV': '"production"' },
  plugins: [oneReact],
  logLevel: 'info',
};

if (process.argv.includes('--watch')) {
  for (const options of [extension, preview]) await (await context(options)).watch();
} else {
  await Promise.all([build(extension), build(preview)]);
}
