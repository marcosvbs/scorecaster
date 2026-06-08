/** One-off build config — no runtime/CI build step (see CLAUDE.md).
 * Regenerate pool/static/pool/tailwind.css whenever template classes change:
 *   tailwindcss -c tailwind.config.js -o pool/static/pool/tailwind.css --minify
 * (standalone CLI v3.x: https://github.com/tailwindlabs/tailwindcss/releases)
 */
module.exports = {
  content: ["pool/templates/**/*.html"],
  theme: {
    extend: {},
  },
  plugins: [],
};
