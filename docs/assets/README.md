# Documentation assets

This folder stores visual media used by GitHub Markdown documentation. Assets document shipped product surfaces and their reproduction inputs; they do not establish benchmark, provider, human-calibration, deployment, usability, or independent-validation evidence.

## Hero

`scaffold-arena-hero.svg` is a deterministic, illustrative diagram of the controlled `offline-demo-v1` workflow. It binds the StudyPack and recorded truth-table inputs, but does not reproduce the full 5-scenario × 16-treatment matrix. Its animation has reduced-motion and light-theme fallbacks, and its title and description state the evidence boundary.

## Product-tour screenshots

The canonical product-tour set contains exactly six surfaces × two viewports under `screenshots/v1/product-tour/`:

| Surface | Desktop (1440 × 900) | Mobile (390 × 844) |
| --- | --- | --- |
| Harness Home / X-Ray | [`harness-home-xray-desktop.png`](screenshots/v1/product-tour/harness-home-xray-desktop.png) | [`harness-home-xray-mobile.png`](screenshots/v1/product-tour/harness-home-xray-mobile.png) |
| Study Canvas | [`study-canvas-desktop.png`](screenshots/v1/product-tour/study-canvas-desktop.png) | [`study-canvas-mobile.png`](screenshots/v1/product-tour/study-canvas-mobile.png) |
| Run Cockpit | [`run-cockpit-desktop.png`](screenshots/v1/product-tour/run-cockpit-desktop.png) | [`run-cockpit-mobile.png`](screenshots/v1/product-tour/run-cockpit-mobile.png) |
| Decision Canvas | [`decision-canvas-desktop.png`](screenshots/v1/product-tour/decision-canvas-desktop.png) | [`decision-canvas-mobile.png`](screenshots/v1/product-tour/decision-canvas-mobile.png) |
| Trace / Counterfactual Lab | [`trace-counterfactual-desktop.png`](screenshots/v1/product-tour/trace-counterfactual-desktop.png) | [`trace-counterfactual-mobile.png`](screenshots/v1/product-tour/trace-counterfactual-mobile.png) |
| Evidence Room | [`evidence-room-desktop.png`](screenshots/v1/product-tour/evidence-room-desktop.png) | [`evidence-room-mobile.png`](screenshots/v1/product-tour/evidence-room-mobile.png) |

The captures use the deterministic `mockWorkbenchV1` fixture. X-Ray is blocked without a captured source; Study Canvas shows `offline-demo-v1`; Run Cockpit is `Execution HOLD`; Decision Canvas and Evidence Room are empty durable-record states; Trace / Counterfactual Lab shows the provider-free replay and Harness CI `HOLD` with unknown usage and no posted comment. No image contains a live provider result, fabricated cost, causal effect, security result, or usability certification.

The browser context uses `deviceScaleFactor=2`, while the canonical PNG writer uses Playwright `scale=css` so fractional responsive grid edges cannot change a single raster pixel between runs. Therefore the manifest records CSS-pixel PNG dimensions (for example, 1440 × 900 for a desktop viewport and 390 × 1053 for the full-page Study Canvas mobile capture); mobile heights vary because these are full-page captures, not cropped viewport images.

Regenerate the canonical files deliberately:

```bash
cd frontend
CAPTURE_DOCUMENTATION_ASSETS=1 npx -y pnpm@10 exec playwright test tests/visual/product-tour-v1.spec.ts --project=visual
```

Then run `uv run --project backend python scripts/check-doc-visual-assets.py --check`. The checker is included in `./scripts/verify-all.sh` and CI. It verifies the exact allowlist, surface IDs, meaningful alt text, routes, viewport and PNG dimensions, PNG SHA-256 digests, pinned source state, generator and fixture hashes, the sorted regular-file hash of `frontend/src`, render-input hashes, and browser identity. A passing check proves only that the checked-in visual bytes and declared deterministic fixture/blocked reproduction contract agree.
