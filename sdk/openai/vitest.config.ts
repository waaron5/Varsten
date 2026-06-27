import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Resolve @varsten/core to its TypeScript source so the test run needs no build
// step. The published package resolves to ../core/dist via the workspace symlink.
export default defineConfig({
  resolve: {
    alias: {
      "@varsten/core": fileURLToPath(new URL("../core/src/index.ts", import.meta.url)),
    },
  },
});
