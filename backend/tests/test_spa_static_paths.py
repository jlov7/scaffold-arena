from __future__ import annotations

from pathlib import Path

from main import build_spa_asset_index, resolve_spa_asset


def test_spa_asset_resolution_stays_within_resolved_static_root(tmp_path: Path) -> None:
    static_root = tmp_path / "static"
    assets = static_root / "assets"
    assets.mkdir(parents=True)
    index = static_root / "index.html"
    asset = assets / "app.js"
    outside = tmp_path / "outside.js"
    index.write_text("shell")
    asset.write_text("asset")
    outside.write_text("outside")
    (assets / "escape.js").symlink_to(outside)

    asset_index = build_spa_asset_index(static_root)

    assert resolve_spa_asset(asset_index, "assets/app.js") == asset.resolve()
    for attempted_path in (
        "../outside.js",
        "%2e%2e/outside.js",
        "%252e%252e/outside.js",
        "/etc/passwd",
        "assets\\app.js",
        "assets/escape.js",
    ):
        assert resolve_spa_asset(asset_index, attempted_path) is None
