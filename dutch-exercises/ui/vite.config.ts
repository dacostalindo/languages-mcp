import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// One self-contained HTML file per view (VIEW=results|explanation|player), written to
// ../dutch_exercises/ui_dist/ so the Python package can serve it without Node. See build.mjs.
const view = process.env.VIEW ?? "results";

export default defineConfig({
  root: "src/views",
  plugins: [viteSingleFile()],
  build: {
    outDir: "../../../dutch_exercises/ui_dist",
    emptyOutDir: false,
    rollupOptions: { input: `src/views/${view}.html` },
  },
});
