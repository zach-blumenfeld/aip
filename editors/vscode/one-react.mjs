// An esbuild plugin: resolve every `react` and `react-dom` import from this folder. The card canvas
// lives in console/src/canvas and would import React from console/node_modules when that is
// installed, the preview's entry from here; two copies of React in one bundle break its hooks.
// esbuild.mjs uses it for dist/preview.js, test/preview.test.js for its server-side render.
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);

export const oneReact = {
  name: 'one-react',
  setup(build) {
    build.onResolve({ filter: /^react(-dom)?(\/.*)?$/ }, (args) => ({ path: require.resolve(args.path) }));
  },
};
