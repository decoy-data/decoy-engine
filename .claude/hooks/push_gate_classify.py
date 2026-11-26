"""Decide whether a Bash command must wait for the Decoy quality gate.

Reads the command on stdin. Exit 0 means gated, exit 10 means not gated, and a
message on stdout means the command is refused outright with that reason. Any
other exit (a crash) is treated as gated by the hook.

Gated: `gh pr create`, and any command that runs `git push` and also carries a
word that can lose work (force, delete, prune, tags, mirror, all, a `+` or `:`
refspec, a tag ref). The scan looks at every word of the whole command, quoted
script bodies included, so it can gate a plain push that sits next to an
unrelated `--all`; that costs a review, never lost work. A gated command that
also changes directory is refused, because the receipt is read from this
worktree only.
"""

from __future__ import annotations

import os
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
CHANGES_DIR = re.compile(
    r"(^|[\s;&|(`'\"])(cd|pushd|popd)(\s|$|;)"
    r"|\s-C\s|--git-dir|--work-tree|GIT_DIR=|GIT_WORK_TREE="
)
REFUSAL = (
    "This command changes directory and also pushes riskily or opens a PR, so it "
    "cannot be checked against this worktree's gate. Run it from the worktree it "
    "acts on, as its own command."
)


def words(text: str) -> list[str]:
    """Every word Bash would pass, plus the words inside quoted script bodies."""
    text = re.sub(r"\\\r?\n", " ", text)
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>")
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        tokens = list(lex)
    except ValueError:
        tokens = text.split()
    out: list[str] = []
    for tok in tokens:
        out.append(tok)
        if any(c.isspace() for c in tok):
            out.extend(words(tok))
    return out


def risky(word: str) -> bool:
    if word.split("=", 1)[0] in RISKY_LONG:
        return True
    if re.match(r"-[A-Za-z0-9]", word):
        # Short flags up to an attached -o value: `-fodeploy=1` forces, `-odeploy=1` does not.
        flags = word[1:].split("o", 1)[0]
        return "f" in flags or "d" in flags
    return (
        word.startswith(("+", ":"))
        or word == "tag"
        or "refs/tags/" in word
        or word.startswith("tags/")
    )


def _after(tokens: list[str], i: int, skip_values: tuple[str, ...]) -> list[str]:
    """The non-option words after position i, skipping the values of named options."""
    rest: list[str] = []
    skip = False
    for w in tokens[i + 1 :]:
        if skip:
            skip = False
        elif w in skip_values:
            skip = True
        elif not w.startswith("-"):
            rest.append(w)
    return rest


def runs(tokens: list[str]) -> tuple[bool, bool]:
    """(runs `git push`, runs `gh pr create`), read from command words, not substrings."""
    push = create = False
    for i, w in enumerate(tokens):
        name = os.path.basename(w)
        if name == "git" and _after(tokens, i, ("-C", "-c"))[:1] == ["push"]:
            push = True
        if name == "gh" and _after(tokens, i, ("-R", "--repo"))[:2] == ["pr", "create"]:
            create = True
    return push, create


def classify(text: str) -> tuple[int, str]:
    tokens = words(text)
    push, create = runs(tokens)
    gated = create or (push and any(risky(w) for w in tokens))
    if not gated:
        return NOT_GATED, ""
    if CHANGES_DIR.search(text):
        return 0, REFUSAL
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
