# Offline fixture demonstration StudyPack

This is a bundled, synthetic, dependency-free protocol-v1 demonstration. It contains
no executable pack code, network call, provider invocation, live result, observed
provider cost, observed latency, or causal-performance conclusion.

It declares a fixture-only recorded harness, a full P/V/R/M binary design (16 arms),
a matched clean/stress pair, a positive control, a deliberately broken negative
control, and an anti-cheat control. Deterministic built-in graders account for 100%
of each scenario's score. The output files are recorded evaluation inputs, not
benchmark results.

Run the complete offline check from the repository root:

```bash
cd backend && uv run pytest tests/study_packs_v1/test_offline_demo_v1.py -q
```

The test verifies directory loading and referenced fixture hashes; ZIP validation,
import, and export with `ProtocolRegistryService`; frozen-spec expansion to 16 arms;
and positive, negative, and anti-cheat control separation. It never starts a provider.

The repository can additionally install the single allowlisted
`bundled_offline_demo_fixture` runtime entry. It accepts only this pack's fixed
scenario hashes, harness configuration, P/V/R/M boolean assignments, and bundled
output hashes. It does not execute archive contents or read a caller-provided
fixture-result map. The harness configuration declares zero recorded fixture usage
and zero fixture cost; the durable ledger remains `unknown` without a central price
reconciliation record.

`fixtures/runtime-truth-table.json` is the checked-in, hash-bound mapping for all
five scenarios and sixteen exact P/V/R/M assignments. Its clean candidate requires
recorded planning and verification; its stressed candidate additionally requires
recorded recovery and memory. Those are synthetic fixture rows and manipulation
receipts, not a causal or provider-performance result.

Claim ceiling: synthetic recorded fixtures and local protocol behavior only. This
pack cannot support provider, empirical, causal, deployment, product, or independent
validation claims. Its fixture runtime gives no provider, empirical, causal,
deployment, product, or independent-validation authority.
