import resolve from "@rollup/plugin-node-resolve";
import typescript from "@rollup/plugin-typescript";
import terser from "@rollup/plugin-terser";
import url from "@rollup/plugin-url";

export default {
  input: "src/bitcoin-miner-card.ts",
  output: {
    file: "dist/bitcoin-miner-card.js",
    format: "es",
    sourcemap: true
  },
  plugins: [
    resolve(),
    url({
      include: ["**/*.ttf", "**/*.png"],
      limit: 0,
      fileName: "[name][extname]"
    }),
    typescript({ tsconfig: "./tsconfig.json" }),
    terser()
  ]
};
