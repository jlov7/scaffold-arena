# Comparison To Existing Tools

Scaffold Arena is not positioned as a replacement for model eval suites, prompt testing tools, observability platforms, or agent frameworks.

| Category | Typical Focus | Scaffold Arena Difference |
| --- | --- | --- |
| Model evals | Compare model capability across tasks. | Holds model fixed and compares scaffolds around it. |
| Prompt testing | Compare prompt variants. | Treats the full orchestration pattern as the unit under test. |
| Observability | Trace and monitor production behavior. | Uses traces as evidence for benchmark failure taxonomy and rerun decisions. |
| Agent frameworks | Build agent workflows. | Evaluates scaffold behavior with deterministic scoring, costs, and trace audit. |

## Boundary

Scaffold Arena can complement these tools by producing protocol artifacts and failure evidence. It should not claim to replace domain-specific evals, production observability, or framework-level runtime guarantees.

## Source-Backed Prior-Art Positioning

The sources below were checked on 2026-09-13. They define relevant capabilities and author-reported research scope. They do not independently validate Scaffold Arena.

| Project | Primary source | What the source establishes | Scaffold Arena boundary |
| --- | --- | --- | --- |
| Harness-Bench | [arXiv:2605.27922](https://arxiv.org/abs/2605.27922) | A preprint studying configuration-level harness effects across shared environments, budgets, and evaluations. | This is direct prior art for the central research question. Arena has no completed live comparison and does not claim that the question, method, or result is new. |
| Inspect | [Official overview](https://inspect.aisi.org.uk/), [Agent bridge](https://inspect.aisi.org.uk/agent-bridge.html), and [changelog](https://inspect.aisi.org.uk/CHANGELOG.html) | Support for third-party Python, custom, and CLI agents, sandbox bridges, approval policies, and transcripts. | Scaffold Arena does not claim to replace Inspect; it can be read as a narrower scaffold-effect protocol with explicit same-model comparisons and product-facing trace evidence. Arena has no demonstrated Inspect integration. |
| Harbor and Terminal-Bench | [Harbor documentation](https://www.harborframework.com/docs), [Harbor repository](https://github.com/harbor-framework/harbor), and [Terminal-Bench](https://github.com/harbor-framework/terminal-bench) | Modular environment, agent, and task interfaces; native agent execution; benchmark task environments and oracle checking. | Arena has no demonstrated Harbor or Terminal-Bench adapter, comparable execution scale, or native external-agent study. |
| promptfoo | [Official documentation](https://www.promptfoo.dev/docs/intro/) | Prompt, model, RAG, and LLM application evaluation with red teaming. | Scaffold Arena does not claim to replace promptfoo; it narrows the unit under test to scaffold/orchestration choices under a fixed model and emits scaffold-specific run artifacts. |
| OpenAI Evals | [Official guide](https://developers.openai.com/api/docs/guides/evals) | Dataset, grader, experiment, and model-system evaluation workflows. | Scaffold Arena does not claim to replace OpenAI Evals; it focuses on scaffold cards, trace audit, cost/latency evidence, and same-model scaffold decomposition. |
| LangSmith | [LangSmith evaluation](https://docs.langchain.com/langsmith/evaluation) | Application evaluation, observability, experiment management, and human feedback workflows. | Scaffold Arena does not claim to replace LangSmith; it uses a local benchmark protocol to test scaffold alternatives rather than production observability or hosted experiment management. |
| LangGraph | [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview) | Stateful agent orchestration with durable execution, streaming, human-in-the-loop, and persistence. | Scaffold Arena does not claim to replace LangGraph; LangGraph helps build agents, while Scaffold Arena evaluates scaffold behavior and failure profiles. |

The defensible present position is a proposed evidence-bounded factorial study protocol: frozen inputs, typed Holds, durable attempt records, deterministic evaluation, and explicit claim ceilings. This repository does not establish that the combination is unique, superior, easier to use, or effective in a completed live study.

## Reviewer Questions

- Does the protocol isolate scaffold effects rather than prompt/provider matrix effects?
- Does the benchmark produce artifact-level evidence beyond a grader score?
- Could a LangGraph implementation be submitted as one scaffold variant under the same protocol?
- Does this release distinguish local fixture integrity from production monitoring, live model performance, and adoption evidence?

## Hard Boundaries

- Scaffold Arena does not claim to replace existing eval, observability, or orchestration tools.
- The comparison is positioning evidence, not external validation evidence.
- Live benchmark claims still require live provider artifacts and independent reproduction.
