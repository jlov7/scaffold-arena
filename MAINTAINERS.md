# Maintainers

Scaffold Arena currently has one active maintainer:

| Maintainer | GitHub | Scope |
| --- | --- | --- |
| Jason Lovell | `@jlov7` | Repository, protocol, evidence, security, releases, product, and governance |

## Maintainer responsibilities

Maintainers are responsible for preserving the project's evidence boundary and for making repository state truthful. In particular, a maintainer must:

- require review and passing checks for protected branches;
- preserve protocol compatibility or publish an explicit migration path;
- keep fixture, live-provider, human-calibrated, cross-model, and independently reproduced evidence separately attributable;
- review changes to authentication, project isolation, adapters, sandboxing, artifacts, exports, retention, and release workflows as security-sensitive;
- reject secret-bearing logs, artifacts, traces, reports, and release bundles;
- ensure generated schemas, package versions, citation metadata, changelog state, tags, and GitHub releases agree;
- publish releases only through the tag-gated workflow;
- disclose limitations, failed arms, withdrawals, and superseding evidence rather than rewriting history;
- maintain a public decision trail through ADRs, pull requests, issues, and changelog entries.

## Review independence

The current single-maintainer structure cannot provide independent review by itself. Until a second trusted maintainer is appointed:

- all changes remain subject to automated verification;
- security-sensitive or claim-bearing changes should seek an external reviewer when practical;
- self-review must be recorded in the pull request, including threat, evidence, compatibility, and rollback considerations;
- no repository receipt or approval should be described as independent validation.

## Adding or removing maintainers

A maintainer change requires a pull request that updates this file and `.github/CODEOWNERS`, states the intended scope, and records any transfer of release or security responsibilities. Removal must also revoke repository, package, deployment, signing, and incident-response access.

## Succession and inactivity

If the active maintainer is unavailable for 90 days, contributors should open a governance issue documenting the maintenance need and proposed interim ownership. Access transfer must be performed through GitHub's account and organization controls; repository files cannot grant platform permissions.

## Security contact

Security reports follow `SECURITY.md`. Maintainer names in this document are not an instruction to publish vulnerability details in a public issue.

## Repository settings are external evidence

`CODEOWNERS` declares intended ownership. It does not prove that branch protection, required reviews, signed commits, tag protection, or environment approvals are enabled. Those controls must be configured and verified in GitHub repository settings.
