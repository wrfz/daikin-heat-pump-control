import { defineConfig } from "vitest/config";

// One ES module with a fixed name, served by the integration; the layouts are
// copied next to it.
export default defineConfig({
  publicDir: "layouts",
  build: {
    outDir: "../custom_components/daikin_heat_pump_control/frontend",
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
    lib: {
      entry: "src/main.ts",
      formats: ["es"],
      fileName: () => "daikin-heat-pump.js",
    },
  },
  test: {
    environment: "happy-dom",
    include: ["test/**/*.test.ts"],
  },
});
