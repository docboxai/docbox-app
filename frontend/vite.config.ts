import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Where the dev server forwards /api when the app runs in a plain browser (lib/api.ts).
const backend = process.env.DOCBOX_BACKEND_URL ?? "http://127.0.0.1:8756";
const proxy = { "/api": { target: backend, changeOrigin: true } };

export default defineConfig({
  plugins: [react(), tailwindcss()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
    proxy,
  },
  preview: { proxy },
});
