#!/usr/bin/env bash
# Decoy pre-PR/push quality gate (PreToolUse hook on Bash).
#
# Blocks `gh pr create` until the Decoy quality gate has passed
# for the EXACT current HEAD. The pass is recorded in .git/decoy-quality-gate by
# decoy-gate-pass.sh, which should be run only after:
#   1. the `dennis` agent reviewed the change (he runs /code-review +
#      /security-review + /qa and returns a verdict) and every BLOCKER/HIGH is
#      resolved, and
#   2. the `barry` agent synced the docs to the change.
#
# The receipt is tied to the commit SHA, so any new commit after the gate
# invalidates it and the gate fires again. This is the local "automatic standard
# while developing" layer; GitHub branch protection is the complementary
# server-side hard gate.
set -euo pipefail

input=$(cat)
cmd=$(printf '%s' "$input" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_input',{}).get('command',''))" \
  2>/dev/null || echo "")

# Owner 2026-11-25: every agent may push, since a push only backs up work; only
# the orchestrator may push main or merge (the user-level branch-only guard
# enforces that). Opening a PR still waits for this gate, and so do pushes that
# can lose work by accident: tags, force, delete, prune, mirror or all. Each
# shell command on the line is checked on its own words, so a plain push next
# to another command is not caught by that command's options.
if ! printf '%s' "$cmd" | python3 -c '
import shlex, sys

RISKY_LONG = {"--tags", "--follow-tags", "--force", "--force-with-lease",
              "--force-if-includes", "--mirror", "--all", "--delete", "--prune"}

def words(text):
    lex = shlex.shlex(text.replace("\\\n", " "), posix=True, punctuation_chars=";&|")
    lex.whitespace_split = True
    seg = []
    for tok in lex:
        if tok and set(tok) <= set(";&|"):
            yield seg
            seg = []
        else:
            seg.append(tok)
    yield seg

def risky_push(args):
    for a in args:
        if a.split("=", 1)[0] in RISKY_LONG:
            return True
        if a.startswith("-") and not a.startswith("--") and set(a[1:]) & {"f", "d"}:
            return True
        if a.startswith("+") or a.startswith(":") or a == "tag" or a.startswith("refs/tags/"):
            return True
    return False

def gated(text):
    for seg in words(text):
        if len(seg) >= 3 and seg[0] == "gh" and seg[1] == "pr" and seg[2] == "create":
            return True
        if "git" in seg:
            i = seg.index("git")
            rest = seg[i + 1:]
            while rest and rest[0].startswith("-"):
                rest = rest[2:] if rest[0] in ("-C", "-c") else rest[1:]
            if rest and rest[0] == "push" and risky_push(rest[1:]):
                return True
    return False

try:
    sys.exit(0 if gated(sys.stdin.read()) else 1)
except ValueError:
    sys.exit(0)
'; then
  exit 0
fi

head=$(git rev-parse HEAD 2>/dev/null || echo "")
git_dir=$(git rev-parse --git-dir 2>/dev/null || echo ".git")
receipt=$(cat "$git_dir/decoy-quality-gate" 2>/dev/null || echo "")

if [ -n "$head" ] && [ "$head" = "$receipt" ]; then
  exit 0
fi

short=${head:0:8}
reason="Decoy quality gate not satisfied for HEAD ${short}. Before pushing or opening a PR: (1) dispatch the 'dennis' agent to review this change (he runs /code-review, /security-review, and /qa and returns a verdict) and resolve every BLOCKER and HIGH; (2) dispatch the 'barry' agent to sync the docs to the change; (3) record the pass: bash .claude/hooks/decoy-gate-pass.sh. Then re-run the push. Committing more after the gate re-arms it, by design."

python3 - "$reason" <<'PY'
import json, sys
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": sys.argv[1],
    }
}))
PY
exit 0
