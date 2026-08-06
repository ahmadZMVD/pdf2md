import { defineConfig } from "vite";

export default defineConfig({
  root: "src",
  publicDir: "public",
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
  },
  build: {
    outDir: "../dist",
    emptyOutDir: true,
  },
});
