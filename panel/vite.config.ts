/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Library build, not React Router framework mode: Home Assistant loads the panel as ONE ES module that
// defines a custom element (panel_custom `module_url`). Framework mode emits an HTML document + hashed
// assets and hydrates the whole document, which cannot live inside HA's own page.
export default defineConfig({
  plugins: [react()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") }, // lib mode doesn't replace it
  build: {
    outDir: "../custom_components/zwave_alarm/frontend",
    emptyOutDir: false,
    cssCodeSplit: false,
    sourcemap: false,
    lib: { entry: "src/main.tsx", formats: ["es"], fileName: () => "zwave-alarm-panel.js" },
    // Vite skips minifying ES library output, so ask rolldown directly: keeps the committed bundle and its diffs small.
    rolldownOptions: { output: { inlineDynamicImports: true, minify: true } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], css: false },
});
