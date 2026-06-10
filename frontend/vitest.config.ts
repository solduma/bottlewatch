// Vitest config: separate from Next/webpack config. We need:
// - jsdom env for React Testing Library
// - the @/* path alias (matches tsconfig.json)
// - globals off (we use explicit imports; matches the rest of the project)
import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  // React 19 + Next 15 use the automatic JSX runtime (no `import React`).
  // Vitest defaults to the classic runtime; pin automatic so .tsx test
  // files don't need a React import.
  esbuild: { jsx: "automatic" },
  test: {
    environment: "jsdom",
    globals: false,
    include: ["app/**/*.test.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
});
