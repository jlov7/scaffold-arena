# External harness adapters

Pi, Prime Agent, and the official DeepSeek Harness are represented by pinned wrappers only. The repository neither installs nor executes upstream software.

| Wrapper | Source | Pin | Claim ceiling |
| --- | --- | --- | --- |
| Pi | `https://github.com/earendil-works/pi` | `v0.84.2` / `914cf1472e715297caa30db4b9535d534a9eb718` | unsandboxed local: protocol-only |
| Prime Agent | `https://github.com/PrimeIntellect-ai/prime-agent` | `v0.7.2` / `83a0f9f9566219551fcb6ffaf7f519a815749a58` | unsandboxed local: protocol-only |
| DeepSeek Harness | `https://github.com/deepseek-ai/deepseek-harness` | developer preview `0.1.0-rc.5` / `47f943859bef60e4160492346772ded9b24f765a` | experimental, protocol-only |

## Wiring

Construct a wrapper with an identity probe and a separately managed `ExternalHarnessTransport`, then install it explicitly into `AdapterRegistry` with the wrapper's `adapter_digest`. The identity probe must return exactly the wrapper's `release.identity()` fields. A failed, absent, or mismatched probe is unhealthy and prevents preparation.

Pi and Prime Agent may support `live_provider` eligibility only when constructed
with both `ExternalOciEvidence` and an injected verifier that revalidates that
exact evidence binding during healthcheck and preparation. Digest-shaped caller
fields alone are not evidence and do not raise the claim ceiling or advertise
remote isolation. This wrapper does not create, inspect, or attest a container;
the declared remote sandbox is never inferred from a local installation. DeepSeek
remains protocol-only even with verified OCI evidence.

The bridge receives the canonical, hash-bound `AttemptInput`. It must return protocol `ResultBundle`, `TraceEvent`, and `ArtifactRef` values. Omitted `ResultBundle.usage` remains unknown; wrappers never synthesize zero usage or costs. Bridges must be configured outside this repository's runtime bootstrap and must not expose credentials through healthcheck diagnostics.
