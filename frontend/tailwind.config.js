/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        surface: {
          light: "#fcfcfb",
          "light-page": "#f9f9f7",
          dark: "#1a1a19",
          "dark-page": "#0d0d0d",
        },
        ink: {
          primary: "#0b0b0b",
          secondary: "#52514e",
          muted: "#898781",
          "dark-primary": "#ffffff",
          "dark-secondary": "#c3c2b7",
        },
        series: {
          portfolio: "#2a78d6",
          "portfolio-dark": "#3987e5",
          spy: "#eb6834",
          "spy-dark": "#d95926",
          qqq: "#4a3aa7",
          "qqq-dark": "#9085e9",
        },
        pos: "#0ca30c",
        "pos-text": "#006300",
        neg: "#d03b3b",
      },
      fontFamily: {
        sans: ["system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [],
};
