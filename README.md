# world-cup-26
World Cup 2026 tracker and prediction platform — follow groups, knockouts, and compete with friends on match forecasts.

## Tailwind CSS

The UI uses a pre-built, committed stylesheet at `pool/static/pool/tailwind.css` — no
runtime/CI build step. Regenerate it whenever template classes change:

```bash
# standalone CLI v3.x: https://github.com/tailwindlabs/tailwindcss/releases
tailwindcss -c tailwind.config.js -o pool/static/pool/tailwind.css --minify
```
