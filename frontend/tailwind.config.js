/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0f17",
        panel: "#131a26",
        panel2: "#1a2333",
        line: "#243044",
        muted: "#8695ad",
        accent: "#4f8cff",
        up: "#22c55e",
        down: "#ef4444",
        warn: "#f59e0b",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
