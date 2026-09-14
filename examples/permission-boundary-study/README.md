# Permission boundary study — mocked project chooser

This example exercises the existing Workbench team chooser with two synthetic
memberships. It verifies that selecting an explicitly authorized membership
updates the `project_id` URL state and that browser history restores it. The
test uses `frontend/tests/support/workbenchV1Mock.ts`; it does not use
credentials, a real tenant, a real account identifier, or a live API.

## Run

From the repository root:

```bash
cd frontend && npx -y pnpm@10 exec playwright test tests/e2e/workbench-v1.spec.ts --grep "team chooser" --output=/tmp/scaffold-arena-permission-boundary-results
```

Expected result: the focused Playwright test passes, with the selected
synthetic `project-a` and `project-b` membership contexts reflected in the
URL. The mocked authorization/client contract is not tenant-isolation proof,
penetration testing, deployment security, or independent assurance. The
focused backend team-authorization tests and the existing accessibility route
check remain the governing companion checks.

Inputs, expected output, a report metadata secret-scan boundary, and cleanup
are pinned in the [example manifest](manifest.json). The smoke test must not
expose secret-like values in page text or report metadata. Remove only the
explicit temporary Playwright output directory after inspection:

```bash
rm -rf /tmp/scaffold-arena-permission-boundary-results
```

There is no dedicated team screenshot in this example-only change. The
[product-tour evidence map](../../docs/product-tour.md) remains the authority
for any fixture-backed UI capture and must not be read as production tenant
isolation evidence.
