from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-claim-boundaries.py"
SPEC = importlib.util.spec_from_file_location("claim_boundaries", SCRIPT)
assert SPEC and SPEC.loader
claims = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(claims)


class ClaimBoundaryTests(unittest.TestCase):
    def test_discovers_every_tracked_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-boundaries-") as temporary:
            root = Path(temporary)
            self._write(root, "README.md", "public\n")
            self._write(root, "docs/scaffolds.md", "public\n")
            self._write(root, "notes.txt", "not Markdown\n")
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            subprocess.run(
                ["git", "-C", str(root), "add", "README.md", "docs/scaffolds.md", "notes.txt"],
                check=True,
            )
            self.assertEqual(claims.tracked_markdown_paths(root), ["README.md", "docs/scaffolds.md"])
            (root / "docs" / "scaffolds.md").unlink()
            self.assertEqual(claims.tracked_markdown_paths(root), ["README.md"])

    def test_scans_the_actual_tracked_markdown_inventory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-boundaries-") as temporary:
            root = Path(temporary)
            safe = "README.md"
            hidden_hole = "docs/scaffolds.md"
            self._write(root, safe, "A testable hypothesis requires empirical study.\n")
            self._write(root, hidden_hole, "| Typical Score | 30-95 |\n")
            errors = claims._check_forbidden_phrases(root, [safe, hidden_hole])
            self.assertTrue(any(hidden_hole in error for error in errors))

    def test_rejects_unsupported_scaffold_score_and_growth_claims(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-boundaries-") as temporary:
            root = Path(temporary)
            path = "docs/scaffolds.md"
            self._write(
                root,
                path,
                "| Typical Score | 30-95 |\n"
                "Quality improvement is usually exponential.\n"
                "The score improvement is often 2-3x.\n",
            )
            errors = claims._check_forbidden_phrases(root, [path])
            self.assertEqual(len(errors), 3)
            self.assertTrue(all(path in error for error in errors))

    def test_allows_hypotheses_negative_warnings_and_fixture_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-boundaries-") as temporary:
            root = Path(temporary)
            path = "docs/boundaries.md"
            self._write(
                root,
                path,
                "Hypothesis: quality improvement may be exponential; this requires empirical study.\n"
                "Do not claim a typical score without comparative evidence.\n"
                "Fixture expected field: Typical Score = 30-95.\n"
                "This fixture does not establish a 2-3x score improvement.\n",
            )
            self.assertEqual(claims._check_forbidden_phrases(root, [path]), [])

    def test_unrelated_disclaimer_does_not_suppress_empirical_score_claim(self) -> None:
        with tempfile.TemporaryDirectory(prefix="claim-boundaries-") as temporary:
            root = Path(temporary)
            path = "docs/scaffolds.md"
            self._write(
                root,
                path,
                "This is not a live benchmark result.\n"
                "| Typical Score | 30-95 |\n",
            )
            errors = claims._check_forbidden_phrases(root, [path])
            self.assertEqual(len(errors), 1)
            self.assertIn("Typical Score", errors[0])

    def _write(self, root: Path, relative_path: str, content: str) -> None:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
