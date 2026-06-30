import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#17202a",
        navy: "#0d1b2a",
        teal: "#F47920",
        green: "#15803d",
        amber: "#b45309",
        red: "#dc2626",
        blue: "#1a3a5c",
        "soft-green": "#f0fdf4",
        "soft-amber": "#fffbeb",
        "soft-red": "#fef2f2",
        "soft-grey": "#f1f5f9",
        paper: "#f9fafb",
        line: "#e2e8f0",
        "kobie-orange": "#F47920",
        "kobie-navy": "#0d1b2a",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: {
        card: "8px",
        pill: "999px",
      },
      boxShadow: {
        panel: "0 12px 28px rgba(23,50,77,0.08)",
        "panel-lg": "0 18px 44px rgba(23,50,77,0.12)",
      },
      keyframes: {
        "dash-flow": {
          to: { strokeDashoffset: "-16" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-ring": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.55" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "dash-flow": "dash-flow 0.6s linear infinite",
        "fade-up": "fade-up 0.4s ease-out both",
        "pulse-ring": "pulse-ring 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
