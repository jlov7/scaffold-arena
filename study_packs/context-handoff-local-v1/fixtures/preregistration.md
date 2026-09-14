# Context-handoff local v1

This frozen synthetic packet studies only delivery of declared context under a
single local model binding. It does not license a performance or causal claim.

The fixed denominator is four scenarios by three context policies by two
repetitions: 24 worker requests. Each has a total context ceiling of 4,096 tokens
and an output ceiling of 256 tokens; reported input above 3,840 is a retained
context-budget HOLD. Aggregate provider input plus output is therefore capped at
98,304 tokens (24 times 4,096), not the output-only allowance of 6,144 tokens.
The aggregate wall-time cap remains 4,320 seconds from durable execution creation;
each request has a 180-second cap. No retries, substitutes, tools, or paid calls.

Expected responses are declared in fixtures/expected.json and bound per scenario
in the StudyPack's exact-field graders. Helpful controls can lack a required
packet label under isolated delivery. Distractor controls give isolated delivery
a sufficient current baseline. Analysis-holdout tasks are visible, fixed before
any inference, and are never used to tune the policies, model, renderer or caps.
