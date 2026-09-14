# Evidence status

Scaffold Arena 0.9.1 is an undeployed beta release candidate. A pre-curation repository gate passed for source tree `bc40b5b9e4d82e74164188d0f44ac3c69ede9863` at base revision `fb22a5bc34f58d0e1d3248b66e9dd3f297720cc5`. That record does not cover later changes: a new candidate requires its own exact-revision gate receipts. The current candidate is not published or deployed. A separate historical deployment-parity check for merge `002fe74fbab99bb5adf611b857b05cfd17dc3f53` is recorded below; it does not apply to a later candidate or establish a current deployment.

| Evidence class | Current state | Supported conclusion |
| --- | --- | --- |
| Protocol and schemas | Validated | Protocol-v1 objects, freezes, hashes, and migrations satisfy the checked contracts. |
| Harness Mechanism Atlas | Validated locally | Source-backed declarations and synthetic metadata fixture shapes are schema- and custody-validated locally. This is not runtime activation, interoperability, safety, deployment, performance, human-calibration, or independent-reproduction evidence. |
| Synthetic fixture study | Validated | The bundled 16-arm, 80-attempt offline study exercises the durable execution-to-evidence path. |
| Automated tests | Validated | Backend, frontend, schema, security, accessibility, and release gates pass on the named revision. |
| X-Ray and observatory contracts | Validated locally | Bounded captured snapshots and persisted fixture traces exercise candidate Genome, ledger, microscope, and fidelity reporting; this is contract/fixture evidence, not a live run, runtime truth, causality, performance, or security evidence. |
| Counterfactual Replay and Harness CI contracts | Candidate fixture/recorded implementation | Checkpointed paired contracts, policy checks, and UI/API/CLI fixture paths preserve HOLD and unknown values. This is not a live replay, causal result, model-performance claim, deployment approval, or independent validation. |
| Arena Forge, planner, and process-safety controls | Candidate provider-free implementation | Strict proposal/approval/evaluation custody, constrained design simulation, digest-only flow controls, and fixture UI/API/CLI paths exercise product controls. They are not a security assessment, containment proof, live model-performance result, deployment approval, or independent validation. |
| Scale model | Analytical only | Integer bounds and storage/index assumptions are checked; this is not a production load test. |
| Native Ollama and LM Studio adapters | Contract-tested and locally exercised | Both adapters bind literal-loopback native APIs, bounded sanitized responses, zero-tool controls, and fail-closed drift checks. Ollama supplies observable runtime/model identity and usage. LM Studio's runtime revision and model-file digest remain operator attestations and cannot satisfy provider-observed identity. |
| Context-handoff local study | Capability implemented; no comparative run recorded | The frozen 24-cell local-only protocol can bind declared context delivery, matched seeds, runtime identity, zero-paid local pricing, and incomplete-cell ledger status. It supports no comparative, causal, cache-saving, transfer, human-calibration, or independent-reproduction claim until a verified run exists. |
| Exploratory local-runtime custody | One derived local-live receipt verified; one typed HOLD | A bounded Ollama `qwen3.5:4b` durable attempt and separate deterministic evaluation completed with 32 input, 6 output, 38 total tokens, zero tools, zero paid cost, unknown energy, and `HOLD / DESCRIPTIVE_ONLY` analysis. LM Studio `qwen3.8-27b` was exercised but correctly withheld from receipt publication because native v1 exposes no verifiable runtime version. See [the exact evidence record](evidence/local-runtime-exploratory-v1.md). |
| Production revision parity | Verified for merge `002fe74fbab99bb5adf611b857b05cfd17dc3f53` | The Vercel frontend and Railway API public build receipts reported the same full merge SHA and the token-free production smoke passed. This establishes deployment revision coherence and public health only, not deployment security, scientific validity, or independent assurance. |
| Flagship and transfer preregistration readiness | Validated offline | Declarative issue #33/#34 StudyPacks, frozen-config and cohort checks, native-local-runtime admission contracts, fixture matrix plans, and custody manifests are checked locally. Their repeated-character digests bind placeholder fixture identities only; confirmatory admission rejects them even if publication metadata is toggled public. The exploratory probes above are not matrix cells. No confirmatory empirical result or signature/publication evidence exists. |
| Live provider study | Not yet recorded | No model or harness performance claim is supported. |
| Human calibration | Not yet completed | Qualitative judge calibration claims remain unavailable. |
| Independent reproduction | Not yet completed | No external-validation or adoption claim is supported. |

Hashes and receipts demonstrate artifact custody and integrity only. They do not prove that an answer is correct, that an evaluator is independent, or that a deployment is secure.

## Historical evidence in a future clean-history snapshot

Normal verification requires a historical local-runtime bundle's recorded code revision to be an ancestor of `HEAD`. That remains the default rule.

If a future public repository is created from a curated snapshot without the older source history, its single root commit may carry one canonical publication binding. The binding must match the snapshot tree and complete Git object inventory, and must pin the raw `bundle-manifest.json` bytes for every retained historical bundle. A missing, malformed, duplicated, noncanonical, unsafe, or mismatched binding fails closed.

Only then can the verifier report `historical_source_revision_unverifiable_in_snapshot`. That status means the retained raw bundle's integrity and custody were checked in the snapshot. It does not reconstruct or reproduce the older source revision, establish current-code ancestry, create a new live run, support a scaffold-effect result, or provide independent validation. No such clean-history snapshot is asserted by this document.

X-Ray reports describe a candidate Genome for a named captured source snapshot. Observatory reports describe bounded observations over named persisted evidence. Inference remains inference; unknown remains unknown; neither report is causal, performance, or security-assurance evidence.

Counterfactual Replay binds declared common inputs and recorded branch references; Harness CI evaluates a bounded policy over that report. `PASS` means only that the declared local policy checks passed over the named evidence. A fixture remains a fixture. The five causal-family measures (ITT, opportunity, activation, fidelity failure, and treatment-on-the-treated) remain explicitly unestimated unless their own assumptions are evidenced.

The beta label remains until a frozen live study, completed blind human calibration, and an independently attributable reproduction are published. These are evidence milestones, not missing product pages or simulated results.
