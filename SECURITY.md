# Security Policy

## Reporting a vulnerability

Please report security issues privately via
[GitHub Security Advisories](https://github.com/iamhimanishah/langgraph-telemetry-fuzzer/security/advisories/new)
rather than opening a public issue. Expect an acknowledgement within a week.

## Scope — what this project is, security-wise

This is an offline evaluation harness. It has no server, no network
listener, no authentication, and no persistence. The realistic risk surface
is small but not empty:

**In scope**

- **Arbitrary code execution via `--agent`.** `ltf run --agent mod:func`
  imports and calls the module you name. That is by design — it is how you
  plug in your agent — but it means `--agent` is equivalent to `python -c`.
  Never pass an agent path from untrusted input.
- **Untrusted telemetry as input.** Telemetry is parsed into Pydantic models
  and never evaluated, but a crash or unbounded memory growth on malformed
  input is a legitimate report.
- **Credential leakage.** The optional `[llm]` and `[judge]` extras read
  `ANTHROPIC_API_KEY`. Any path that writes a key into a report, log line, or
  `--json-out` file is a bug — please report it.
- **The MCP server** (`mcp_guardrail/`) if run exposed. It serves bundled
  fixtures over stdio and is intended for local use.

**Out of scope**

- Prompt injection *through telemetry content* against an agent under test.
  That is arguably the point of the harness rather than a flaw in it — if you
  find telemetry that reliably steers an agent, that is an interesting
  scenario contribution, not a vulnerability.
- The judgement scores being wrong for your agent. That is a correctness
  discussion; open an issue.

## Handling secrets

The harness never persists credentials. If you contribute a feature that
touches an API key, keep it in the environment, never in `Telemetry`,
`AgentVerdict`, or anything reachable from `to_json_dict()` — the JSON report
is the most likely place for a secret to escape unnoticed.
