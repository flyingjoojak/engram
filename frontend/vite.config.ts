import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    // 개발 중 FastAPI 백엔드로 프록시(python -m vestige.web = 127.0.0.1:8642)
    proxy: { "/api": "http://127.0.0.1:8642" },
  },
})
