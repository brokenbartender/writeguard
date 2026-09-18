# writeguard

**Verify your AI coding agent actually did what it claims to the filesystem.**

LLM coding agents hallucinate file changes. They report *"I've updated `config.py`"* when no
write ever happened, or claim a modification that left the file byte-for-byte identical.
`writeguard` catches it: snapshot the files before the agent runs, then verify each claimed
operation against real disk state with SHA-256, and get back a correction prompt for the ones
that lied. Framework-agnostic — it checks the **disk**, not the agent's words.

```bash
pip install writeguard
```

```python
from writeguard import snapshot, verify, catch_phantom_write

# 1. Snapshot the files the agent might touch — before it runs
before = snapshot(["config.py", "main.py"])

# ... your agent runs and claims it created config.py and modified main.py ...

# 2. Verify those claims against what's actually on disk
result = verify(
    [{"path": "config.py", "op": "create"},
     {"path": "main.py",   "op": "modify"}],
    before,
)

if not result.ok:
    print(result.correction_prompt)   # feed this back to the agent to make it fix reality
```

## Why

Autonomous agents (and long chat sessions) routinely claim edits they never made. The failure is
silent: the agent says "done," the run "succeeds," and the file is untouched. Tool-execution logs
help — but only if the agent actually *called* the tool. `writeguard` verifies against ground
truth (the filesystem) regardless of what the agent says or which framework it uses.

## What it checks

| Op | VERIFIED when… | FAILED / DRIFT when… |
|----|----------------|----------------------|
| `create` | file now exists (and matches `content_hash` if given) | not created (FAILED); already existed / wrong hash (DRIFT) |
| `modify` | file changed on disk | missing (FAILED); byte-identical to before (DRIFT) |
| `delete` | file is gone | still exists (FAILED); never existed (DRIFT) |
| `read` | file exists | missing (FAILED) |

## The phantom-write heuristic

A cheap pre-check before you even run `verify()` — catch an agent that *says* it wrote a file in
prose while calling no write tool:

```python
from writeguard import catch_phantom_write

warning = catch_phantom_write(agent_message, tool_called=last_tool_name)
if warning:
    print(warning)   # "You claimed to change a file (...) but no write tool was executed."
```

## Detect silent drift

Find files that changed on disk but the agent never mentioned:

```python
from writeguard import snapshot, detect_unexpected_changes

before = snapshot(["a.py", "b.py", "c.py"])
# ... agent claims it only touched a.py ...
sneaky = detect_unexpected_changes(before, claimed_paths=["a.py"])
# → ["/abs/path/b.py"] if b.py changed unexpectedly
```

## Path containment

When paths come from untrusted model output, restrict snapshots to a root so a traversal
(`../../etc/passwd`) can't be read:

```python
before = snapshot(agent_paths, root="./workspace")   # anything outside ./workspace → not captured
```

## Design

- **Zero dependencies.** Pure standard library. Python 3.9+.
- **Framework-agnostic.** Works with OpenAI, Claude, LangChain, LlamaIndex, or a custom loop —
  it verifies the disk, so it doesn't care how your agent is built.
- **Deterministic.** SHA-256 content hashing; no models, no network.

## Install & test

```bash
pip install writeguard
python -m pytest tests/ -v   # 10 tests, fully offline
```

## License

MIT
