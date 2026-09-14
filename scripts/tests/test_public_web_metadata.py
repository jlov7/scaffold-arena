from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
INDEX = ROOT / "frontend" / "index.html"
HYGIENE = ROOT / "scripts" / "check-public-repo-hygiene.py"


def load_hygiene_module():
    spec = importlib.util.spec_from_file_location("public_repo_hygiene", HYGIENE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicWebMetadataTests(unittest.TestCase):
    def test_public_metadata_uses_canonical_site_and_evidence_bounded_copy(self) -> None:
        html = INDEX.read_text(encoding="utf-8")
        lowered = html.lower()

        self.assertIn('href="https://scaffold-arena.vercel.app/"', html)
        self.assertIn('content="https://scaffold-arena.vercel.app/"', html)
        self.assertIn('content="https://scaffold-arena.vercel.app/og-image.png"', html)
        self.assertIn('property="og:image:alt"', html)
        self.assertIn('name="twitter:image:alt"', html)
        self.assertIn('name="theme-color"', html)
        self.assertNotIn("scaffold-arena.example", lowered)
        self.assertNotIn("prove orchestration wins", lowered)
        self.assertNotIn("live arena runs", lowered)
        self.assertIn("controlled experiments", lowered)
        self.assertIn("evidence", lowered)
        self.assertIn("ai harness engineering", lowered)

    def test_public_hygiene_rejects_placeholder_and_unbounded_html_claims(self) -> None:
        module = load_hygiene_module()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            page = root / "index.html"
            page.write_text(
                '<meta property="og:url" content="https://scaffold-arena.example">'
                '<meta name="description" content="Prove orchestration wins with live arena runs">',
                encoding="utf-8",
            )
            errors = module.scan_public_content(root, ["index.html"])

        self.assertEqual(
            errors,
            [
                "index.html: contains placeholder production URL",
                "index.html: contains unsupported live-win claim",
                "index.html: contains unsupported live-run claim",
            ],
        )


if __name__ == "__main__":
    unittest.main()
