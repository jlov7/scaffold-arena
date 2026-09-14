from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCANNER = ROOT / "scripts" / "scan-secrets.sh"


class ScanSecretsTests(unittest.TestCase):
    def test_sensitive_env_is_denied_before_reading(self) -> None:
        secret = "ghp_" + "a" * 30
        for relative in (
            "backend/.env.production",
            "backend/.ENV.production",
            "private/CREDENTIALS/token.txt",
            "private/ID_RSA",
            "private/deploy.KEY",
        ):
            with self.subTest(relative=relative):
                result = self._scan({relative: "token = \"" + secret + "\"\n"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(relative, result.stdout)
                self.assertNotIn(":1", result.stdout)
                self.assertNotIn(secret, result.stdout)

    def test_env_example_and_ordinary_source_are_scanned_without_secret_echoes(self) -> None:
        secret = "ghp_" + "a" * 30
        for relative in ("backend/.env.example", "docs/source.txt"):
            with self.subTest(relative=relative):
                result = self._scan({relative: "token = \"" + secret + "\"\n"})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(relative + ":1", result.stdout)
                self.assertNotIn(secret, result.stdout)

    def test_ordinary_files_pass_and_deleted_tracked_file_fails_closed(self) -> None:
        result = self._scan({"docs/ordinary.txt": "public example\n"})
        self.assertEqual(result.returncode, 0, result.stderr)
        with tempfile.TemporaryDirectory(prefix="scan-secrets-") as temporary:
            root = Path(temporary)
            self._write(root, "docs/deleted.txt", "removed before scan\n")
            self._git(root, "init", "--quiet")
            self._git(root, "add", "docs/deleted.txt")
            (root / "docs/deleted.txt").unlink()
            result = subprocess.run(
                ["bash", str(SCANNER), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("docs/deleted.txt", result.stdout)

    def test_helper_failure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="scan-secrets-") as temporary:
            root = Path(temporary)
            copied_scanner = root / "runner" / "scan-secrets.sh"
            copied_scanner.parent.mkdir()
            copied_scanner.write_bytes(SCANNER.read_bytes())
            copied_scanner.chmod(0o700)
            self._write(root, "docs/ordinary.txt", "public example\n")
            self._git(root, "init", "--quiet")
            self._git(root, "add", ".")
            result = subprocess.run(
                ["bash", str(copied_scanner), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("content scanner could not complete safely", result.stderr)

    def _scan(self, files: dict[str, str]) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(prefix="scan-secrets-") as temporary:
            root = Path(temporary)
            for relative, content in files.items():
                self._write(root, relative, content)
            self._git(root, "init", "--quiet")
            self._git(root, "add", ".")
            return subprocess.run(
                ["bash", str(SCANNER), "--root", str(root)],
                check=False,
                capture_output=True,
                text=True,
            )

    def _git(self, root: Path, *arguments: str) -> None:
        subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)

    def _write(self, root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
