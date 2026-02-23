# Documentation Assets

This folder stores visual media used by the repository documentation.

## Screenshot Source

Screenshots are generated from the frontend using a deterministic mocked API flow:

```bash
cd frontend
node scripts/capture-doc-screenshots.mjs
```

Generated files:
- `screenshots/*.png`
- `walkthrough.gif`

## Illustration Source

- `illustrations/system-map.svg`
- `illustrations/value-flywheel.svg`
- `illustrations/system-map.png`
- `illustrations/value-flywheel.png`

Use the PNG files in README/docs for maximum renderer compatibility (GitHub web/mobile and repo previews). Keep SVG files as editable sources.
