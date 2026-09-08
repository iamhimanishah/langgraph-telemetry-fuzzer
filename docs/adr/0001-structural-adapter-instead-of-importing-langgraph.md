# 1. Adapt to agents structurally, rather than importing LangGraph

- **Status:** Accepted
- **Date:** 2026-07-27

## Context

The harness has to run somebody else's agent. The obvious way to do that
in a project named `langgraph-telemetry-fuzzer` is to `import langgraph`,
type against `CompiledGraph`, and be done.

That has two costs that only show up later. It makes `langgraph` a hard
dependency of the *measurement* code, so anyone wanting to evaluate a
non-LangGraph agent has to install a framework they don't use. And it
couples the harness to a fast-moving library's internal types — a rename
in LangGraph becomes a break in an eval tool that has no business caring.

The deeper point: what this harness actually needs from an agent is
tiny. Hand it telemetry, get back a verdict. That is one method.

## Decision

Define the agent contract structurally, as a `Protocol`:

```python
class InvocableGraph(Protocol):
    def invoke(self, state: dict[str, Any]) -> dict[str, Any]: ...
```

`LangGraphAdapter` wraps anything satisfying it, reading telemetry from
`telemetry_key` and a verdict from `verdict_key` (both configurable).
The harness never imports `langgraph`. It is an optional extra,
`[langgraph]`, needed only to run the agents in `examples/`.

Agents are named on the CLI as `module:function`, where the function
takes no arguments and returns the compiled graph.

## Consequences

The core package installs with just Pydantic. `pytest` runs offline,
and CI does not pull a framework to test corruption injectors.

Any object with `.invoke(dict) -> dict` works — a LangGraph graph, a
plain class, a lambda-ish shim around an HTTP call to a hosted agent.
Several tests exercise the harness with two-line fake agents, which is
only possible because the contract is this thin.

The cost is that mistakes surface at runtime rather than at import. If
your graph returns the verdict under the wrong key, you learn when it
runs. The adapter raises with the key it looked for, which is the
mitigation, not a fix.

`--agent module:function` also means the harness imports and calls
arbitrary named code — equivalent to `python -c`. That is documented in
[SECURITY.md](../../SECURITY.md) rather than defended against; a tool
that runs your agent cannot also refuse to run your code.

## Alternatives rejected

**A base class contributors subclass.** Inverts the dependency the wrong
way: your agent would import the harness. An eval tool should be
attachable to code that has never heard of it.

**Import `langgraph` and type against `CompiledGraph`.** Buys editor
completion on a type we call one method on, in exchange for a hard
dependency and version coupling.
