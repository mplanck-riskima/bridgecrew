/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        lcars: {
          orange: "#FF9900",
          amber:  "#FFCC44",
          blue:   "#6699FF",
          cyan:   "#99CCFF",
          red:    "#CC2200",
          green:  "#33AA55",
          purple: "#CC99FF",
          bg:     "#080c14",
          panel:  "#0d1525",
          border: "#1e3354",
          text:   "#CCDDFF",
          muted:  "#4466AA",
        },
      },
      fontFamily: {
        lcars: ["'Exo 2'", "sans-serif"],
        mono:  ["'Share Tech Mono'", "monospace"],
      },
    },
  },
  plugins: [],
};
