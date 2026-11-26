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
from collections.abc import Iterator

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
CONTROL = ";&|()\n"
PUNCTUATION = CONTROL + "<>"
GIT_VALUE_OPTIONS = ("-C", "-c", "--git-dir", "--work-tree")
SHELLS = {"bash", "sh", "zsh", "dash"}
REFUSAL = (
    "This command changes directory and also pushes riskily or opens a PR, so it "
    "cannot be checked against this worktree's gate. Run it from the worktree it "
    "acts on, as its own command."
)


def script_body(tokens: list[str]) -> str | None:
    args = iter(tokens)
    for word in args:
        if word in {"if", "then", "else", "elif", "while", "until", "do", "!", "env", "command"}:
            continue
        if re.match(r"[A-Za-z_][A-Za-z_0-9]*=", word):
            continue
        if word == "eval":
            return " ".join(args)
        if os.path.basename(word) in SHELLS:
            for option in args:
                if option in {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}:
                    next(args, None)
                    continue
                if option.startswith("--") and option != "--":
                    continue
                if not re.fullmatch(r"-[a-zA-Z]+", option):
                    break
                if "c" in option:
                    return next(args, None)
                if option.endswith(("o", "O")):
                    next(args, None)
        break
    return None


def commands(text: str) -> Iterator[tuple[list[str], bool]]:
    """Yield one word list per script, with its fail-closed verdict on lexer errors."""
    text = re.sub(r"\\\r?\n", " ", text)
    lex = shlex.shlex(text, posix=True, punctuation_chars=PUNCTUATION)
    lex.whitespace = " \t\r"
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        tokens = list(lex)
    except ValueError:
        # Quoting is unreliable here. Keep directory markers and gate on a mention.
        words = re.findall(r"""[^\s;&|()<>'"]+""", text)
        yield words, bool(re.search(r"\bpush\b|\bpr\s+create\b", text))
        return

    yield tokens, False
    command: list[str] = []
    for token in [*tokens, ";"]:
        if token and all(c in CONTROL for c in token):
            if command:
                body = script_body(command)
                if body:
                    yield from commands(body)
                command = []
        else:
            command.append(token)


def changes_dir(word: str) -> bool:
    return word in {"cd", "pushd", "popd", "-C", "--git-dir", "--work-tree"} or word.startswith(
        ("--git-dir=", "--work-tree=", "GIT_DIR=", "GIT_WORK_TREE=")
    )


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
        if name == "git" and _after(tokens, i, GIT_VALUE_OPTIONS)[:1] == ["push"]:
            push = True
        if name == "gh" and _after(tokens, i, ("-R", "--repo"))[:2] == ["pr", "create"]:
            create = True
    return push, create


def classify(text: str) -> tuple[int, str]:
    push = gated = risk = changed_dir = False
    for tokens, fallback_gate in commands(text):
        runs_push, creates_pr = runs(tokens)
        push |= runs_push
        gated |= creates_pr or fallback_gate
        risk |= any(risky(w) for w in tokens)
        changed_dir |= any(changes_dir(w) for w in tokens)
    if not (gated or (push and risk)):
        return NOT_GATED, ""
    if changed_dir:
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
