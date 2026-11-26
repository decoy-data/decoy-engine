"""Decide whether a Bash command must wait for the Decoy quality gate.

Reads the command on stdin. Exit 0 means gated, exit 10 means not gated, and a
message on stdout means the command is refused outright with that reason. Any
other exit (a crash) is treated as gated by the hook.

Gated: `gh pr create`, and any command that runs `git push` and also carries a
word that can lose work (force, delete, prune, tags, mirror, all, a `+` or `:`
refspec, a tag ref). The scan looks at every word of the whole command, so it
can gate a plain push that sits next to an unrelated `--all`; that costs a
review, never lost work. A risky push that also changes directory is refused,
because the receipt is read from this worktree only.
"""

from __future__ import annotations

import re
import shlex
import sys

NOT_GATED = 10
RISKY_LONG = (
    "--tags",
    "--follow-tags",
    "--force",
    "--force-with-lease",
    "--force-if-includes",
    "--mirror",
    "--all",
    "--delete",
    "--prune",
)
GIT_PUSH = re.compile(r"\bgit\b.*\bpush\b", re.DOTALL)
PR_CREATE = re.compile(r"\bgh\b.*\bpr\b.*\bcreate\b", re.DOTALL)
CHANGES_DIR = re.compile(
    r"(^|[\s;&|(])(cd|pushd)\s|\s-C\s|--git-dir|--work-tree|GIT_DIR=|GIT_WORK_TREE="
)


def words(text: str) -> list[str]:
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
    lex.whitespace_split = True
    lex.commenters = ""
    return list(lex)


def risky(word: str) -> bool:
    if word.split("=", 1)[0] in RISKY_LONG:
        return True
    if re.fullmatch(r"-[A-Za-z]+", word):
        letters = word[1:].split("o", 1)[0]
        return "f" in letters or "d" in letters
    return (
        word.startswith(("+", ":"))
        or word == "tag"
        or "refs/tags/" in word
        or word.startswith("tags/")
    )


def classify(text: str) -> tuple[int, str]:
    if PR_CREATE.search(text):
        return 0, ""
    if not GIT_PUSH.search(text):
        return NOT_GATED, ""
    try:
        tokens = words(text)
    except ValueError:
        return 0, ""
    if not any(risky(w) for w in tokens):
        return NOT_GATED, ""
    if CHANGES_DIR.search(text):
        return 0, (
            "A risky push (force, delete, prune, tags, mirror or all) that also "
            "changes directory cannot be checked against this worktree's gate. "
            "Run it from the worktree it pushes, as its own command."
        )
    return 0, ""


def main() -> int:
    code, message = classify(sys.stdin.read())
    if message:
        print(message)
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
