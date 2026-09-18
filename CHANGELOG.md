# Changelog

## [0.1.0] - 2026-09-18
### Added
- Initial release: hash-based verification of AI coding-agent filesystem claims
- `snapshot`, `verify` (create/modify/delete/read), `detect_unexpected_changes`
- `catch_phantom_write` heuristic for prose-claimed writes with no tool call
- Optional path containment (`root=`) against traversal from untrusted model output
- Zero dependencies, Python 3.9+
