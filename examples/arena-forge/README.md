# Arena Forge provider-free fixtures

These fixtures exercise only strict contract validation, bounded design simulation,
and digest-only process-safety controls. They do not invoke a provider, tool,
network request, patch, merge, or sealed-holdout inspection.

```bash
arena forge proposal --input examples/arena-forge/proposal.json
arena forge plan --input examples/arena-forge/planner-exploratory.json
arena forge process-safety --input examples/arena-forge/process-safety-pass.json
```

The proposal intentionally returns `HOLD`: it remains untrusted until a
project-scoped, independent human or policy approval. A planner `READY` result
only means its input designs fit the declared constraints. A process-safety
`PASS` is a product-control record, not a security or containment assessment.
