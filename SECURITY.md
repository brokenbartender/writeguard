# Security Policy

writeguard reads file metadata and content hashes locally; it makes no network calls and stores
nothing. If paths are sourced from untrusted model output, pass `root=` to `snapshot()` to keep
verification inside a directory.

**Reporting:** please report vulnerabilities privately via a GitHub Security Advisory
(Security tab → "Report a vulnerability"), not a public issue.
