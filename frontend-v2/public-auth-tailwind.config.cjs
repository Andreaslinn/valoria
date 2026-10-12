

const config = {
 important: ".public-login",
 corePlugins: {preflight:false},
  content: ["./src/app/login/page.tsx", "./src/components/ui/public-*.tsx"],
  theme: {
    extend: {
      colors: {
        ink: "#f8fafc",
        muted: "#94a3b8",
        line: "rgba(148, 163, 184, 0.18)",
        surface: "#050914",
        brand: {
          50: "rgba(124, 92, 255, 0.12)",
          100: "rgba(124, 92, 255, 0.2)",
          500: "#7c5cff",
          600: "#6246ea",
          700: "#4f35cc",
          900: "#24115f",
        },
        accent: {
          500: "#3ddc97",
          600: "#21b978",
        },
        amber: {
          500: "#f2b84b",
        },
        danger: {
          500: "#ff6b6b",
        },
      },
      boxShadow: {
        soft: "0 22px 70px rgba(0, 0, 0, 0.34)",
        glow: "0 0 42px rgba(124, 92, 255, 0.2)",
      },
    },
  },
  plugins: [],
};

module.exports=config;
