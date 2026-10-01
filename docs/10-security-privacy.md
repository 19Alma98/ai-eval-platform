# Security and Privacy

## Trust model (v0.1)

The platform is **self-hosted and network-trusted by default**.

Access control for v0.1 is an **infrastructure concern**:
- bind to localhost for local demos;
- place behind VPN / private cluster network;
- terminate TLS and identity at a reverse proxy when exposing beyond trusted networks.

Built-in authentication, SSO, and RBAC are explicitly out of scope for MVP.

## Threat model

Primary risks:
- prompt/response data leakage
- malicious telemetry payloads
- SSRF through provider/tool metadata
- oversized payloads
- arbitrary evaluator code
- secret leakage
- unsafe rendering of model output
- accidental exposure of an unauthenticated stack on a public network

## Rules

1. Never execute evaluator code received from users.
2. Custom evaluators are trusted Python packages in v0.1.
3. Limit payload sizes.
4. Sanitize/escape rendered content.
5. Provider credentials are server-side secrets.
6. Never log API keys or provider secrets.
7. Allow content capture to be disabled.
8. Provide redaction hooks.
9. Validate URLs if remote resources are ever supported.
10. Use dependency scanning in CI.
11. Document that public exposure without an external auth layer is unsupported.
12. Prefer fail-closed defaults for content capture and retention.

## Data classification

Trace fields should be classified:
- metadata
- operational
- potentially sensitive content
- secret/prohibited

Input/output content is opt-in.

## Future (optional platform overlays)

These remain optional and should not reshape the domain core:

- optional API key / reverse-proxy identity header
- workspace RBAC
- SSO/OIDC
- encryption-at-rest documentation
- audit logs
- configurable retention
