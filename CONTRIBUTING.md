# Contributing to writeguard

Thanks for helping. This library is deliberately **small and single-purpose** — verify AI-agent
filesystem claims against disk. Please keep it that way; new detection/verification helpers are
welcome, a plugin platform is not.

- `pip install -e . pytest && pytest tests/ -v` before opening a PR
- Add a test for any behavior change
- Keep zero runtime dependencies (standard library only)
