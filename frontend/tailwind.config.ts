import type { Config } from "tailwindcss";

export default {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        regime: {
          peaking: "#f59e0b",
          peaked: "#ef4444",
          resolving: "#10b981",
          emerging: "#3b82f6",
          stable: "#6b7280",
          noData: "#d1d5db",
        },
      },
    },
  },
  plugins: [
    require("@tailwindcss/typography"),
  ],
} satisfies Config;
