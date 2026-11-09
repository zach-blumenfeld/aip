import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The bundle is served at the root by the console's own process (bin/aip-console.mjs). In development,
// run that process too (`node bin/aip-console.mjs --server URL --port 4280`, after one `npm run build`)
// and Vite proxies its /console endpoints to it (CONSOLE, default http://localhost:4280); the page
// calls the AIP server directly either way.
const launcher = process.env.CONSOLE ?? "http://localhost:4280";

export default defineConfig({
  base: "/",
  plugins: [react()],
  server: {
    port: Number(process.env.PORT ?? 5173),
    strictPort: true,
    proxy: { "/console": { target: launcher, changeOrigin: true } },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
