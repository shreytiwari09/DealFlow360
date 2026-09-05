import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    // host:true is required for the dev server to be reachable from outside
    // the container; usePolling is required for HMR to see edits made on a
    // Windows host through a bind mount.
    host: true,
    port: 5173,
    watch: { usePolling: true },
  },
});
