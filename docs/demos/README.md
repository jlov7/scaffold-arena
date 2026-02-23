# Executable Demos

These demos are generated with Showboat and include command output and visual evidence.

## Available demos

- [Production live demo](production-live-verified.md)
  - Proves deployed frontend/backend reachability, security headers, and CORS wiring.
  - Includes a live Rodney browser capture from production.

## Regenerate or verify

From repo root:

```bash
uvx showboat verify docs/demos/production-live-verified.md
```

If you want to capture a fresh browser image, rerun the Rodney capture flow and update the Showboat document.
