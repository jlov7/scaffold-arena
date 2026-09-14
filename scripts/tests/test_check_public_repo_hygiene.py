from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-public-repo-hygiene.py"
SPEC = importlib.util.spec_from_file_location("public_repo_hygiene", SCRIPT)
assert SPEC and SPEC.loader
hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hygiene)


class PublicRepositoryHygieneTests(unittest.TestCase):
    def test_clean_public_tree_passes(self) -> None:
        with self._repository() as root:
            paths = self._required_tree(root)
            self.assertEqual(hygiene.audit(root, paths), [])

    def test_rejects_private_plans_and_machine_local_references(self) -> None:
        with self._repository() as root:
            paths = self._required_tree(root)
            private_plan = "docs/superpowers/plans/internal.md"
            self._write(root, private_plan, "private plan\n")
            hidden_private_plan = "docs/.superpowers/plans/internal.md"
            self._write(root, hidden_private_plan, "private plan\n")
            machine_reference = "docs/reference.md"
            self._write(root, machine_reference, "open /" + "Users/alice/private.txt\n")
            errors = hygiene.audit(root, paths + [private_plan, hidden_private_plan, machine_reference])
            self.assertTrue(any(private_plan in error for error in errors))
            self.assertTrue(any(hidden_private_plan in error for error in errors))
            self.assertTrue(any(machine_reference in error for error in errors))

    def test_rejects_retained_internal_plan_and_private_paths_in_any_utf8_file(self) -> None:
        with self._repository() as root:
            paths = self._required_tree(root)
            retained_plan = "specs/trace-driven-frontier-audit_plan.md"
            self._write(root, retained_plan, "implementation sequence\n")
            log = "logs/retained-actions.log"
            self._write(root, log, "runner path: /" + "Users/alice/actions/workspace\n")
            code_fixture = "backend/tests/retained_path_fixture.py"
            self._write(root, code_fixture, 'PATH = "/' + 'Users/alice/private"\n')
            private_tmp = "backend/tests/private_tmp_fixture.py"
            self._write(root, private_tmp, 'PATH = "/' + 'private/tmp/session"\n')
            var_folders = "outputs/local-path.json"
            self._write(root, var_folders, '{"path":"/' + 'var/folders/x/private"}\n')
            errors = hygiene.audit(root, paths + [retained_plan, log, code_fixture, private_tmp, var_folders])
            self.assertTrue(any(retained_plan in error for error in errors))
            self.assertTrue(any(log in error for error in errors))
            self.assertTrue(any(code_fixture in error for error in errors))
            self.assertTrue(any(private_tmp in error for error in errors))
            self.assertTrue(any(var_folders in error for error in errors))

    def test_allows_only_the_named_machine_path_scanner_fixture(self) -> None:
        with self._repository() as root:
            paths = self._required_tree(root)
            allowed = next(iter(hygiene.LOCAL_REFERENCE_FIXTURE_PATHS))
            self._write(root, allowed, "/" + "Users/tester/fixture-only\n")
            unallowed = "scripts/tests/fixtures/public_hygiene/other-machine-local-reference.txt"
            self._write(root, unallowed, "/" + "Users/tester/not-allowlisted\n")
            allowed_errors = hygiene.audit(root, paths + [allowed])
            unallowed_errors = hygiene.audit(root, paths + [unallowed])
            self.assertEqual(allowed_errors, [])
            self.assertTrue(any(unallowed in error for error in unallowed_errors))

    def test_allows_allowlisted_scaffold_arena_tmp_command_examples(self) -> None:
        with self._repository() as root:
            paths = self._required_tree(root)
            readme = "README.md"
            self._write(root, readme, "arena demo --path /tmp/scaffold-arena-demo\n")
            self.assertEqual(hygiene.audit(root, paths), [])
            allowed = "docs/reference.md"
            self._write(root, allowed, "arena demo --path /tmp/scaffold-arena-provenance.json\n")
            self.assertEqual(hygiene.audit(root, paths + [allowed]), [])
            disallowed = "docs/private-reference.md"
            self._write(root, disallowed, "open /tmp/private-export\n")
            errors = hygiene.audit(root, paths + [disallowed])
            self.assertTrue(any(disallowed in error for error in errors))

    def test_rejects_personal_email_secret_names_content_and_symlinks(self) -> None:
        with self._repository() as root:
            paths = self._required_tree(root)
            email = "docs/contact.md"
            self._write(root, email, "contact " + "jase.lovell" + "@me.com\n")
            secret_name = "keys/deploy.key"
            self._write(root, secret_name, "placeholder\n")
            secret_content = "docs/key.md"
            self._write(root, secret_content, "-----BEGIN " + "RSA PRIVATE KEY-----\n")
            env_production = "backend/.env.production"
            self._write(root, env_production, "/" + "Users/alice/private\n")
            env_example = "backend/.env.example"
            self._write(root, env_example, "/" + "Users/alice/example\n")
            symlink = Path(root) / "docs" / "linked.md"
            symlink.symlink_to(Path(root) / "README.md")
            errors = hygiene.audit(
                root,
                paths + [email, secret_name, secret_content, env_production, env_example, "docs/linked.md"],
            )
            self.assertTrue(any(email in error for error in errors))
            self.assertTrue(any(secret_name in error for error in errors))
            self.assertTrue(any(secret_content in error for error in errors))
            self.assertTrue(any("secret or credential filename: " + env_production in error for error in errors))
            self.assertFalse(any("machine-local reference: " + env_production in error for error in errors))
            self.assertTrue(any("machine-local reference: " + env_example in error for error in errors))
            self.assertTrue(any("docs/linked.md" in error for error in errors))

    def test_rejects_unapproved_root_missing_required_documents_and_fixture_live_escalation(self) -> None:
        with self._repository() as root:
            paths = self._required_tree(root)
            root_file = "notes.txt"
            self._write(root, root_file, "not allowlisted\n")
            escalation = "docs/claims.md"
            self._write(root, escalation, "This fixture proves live provider performance.\n")
            errors = hygiene.audit(root, [path for path in paths if path != "docs/evidence-status.md"] + [root_file, escalation])
            self.assertTrue(any(root_file in error for error in errors))
            self.assertTrue(any("docs/evidence-status.md" in error for error in errors))
            self.assertTrue(any(escalation in error for error in errors))

    def _repository(self):
        return tempfile.TemporaryDirectory(prefix="public-repo-hygiene-")

    def _required_tree(self, root: str) -> list[str]:
        directory = Path(root)
        paths = sorted({"README.md", *hygiene.REQUIRED_PUBLIC_DOCUMENTS, *hygiene.REQUIRED_CONTENT})
        for path in paths:
            markers = hygiene.REQUIRED_CONTENT.get(path, ())
            self._write(directory, path, "public content\n" + "\n".join(markers))
        return paths

    def _write(self, root: Path | str, relative_path: str, content: str) -> None:
        path = Path(root) / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
