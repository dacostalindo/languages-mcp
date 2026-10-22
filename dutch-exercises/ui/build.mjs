// Builds each view into a single HTML file in ../dutch_exercises/ui_dist/.
import { build } from "vite";

for (const view of ["results", "explanation", "player"]) {
  process.env.VIEW = view;
  await build({ configFile: "vite.config.ts", logLevel: "warn" });
  console.log(`built ${view}.html`);
}
