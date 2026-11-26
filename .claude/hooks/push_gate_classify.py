"""Decide whether a Bash command must wait for the Decoy quality gate.

Reads the command on stdin. Prints the directory whose HEAD and receipt the
gate must check, one per line, and exits 0 when the command is gated. Exits 1
when nothing in it is gated. A command the parser cannot read is gated in the
current directory, so a parsing gap never lets a risky push through.

Gated: `gh pr create`, and a `git push` that can lose work by accident (force,
delete, prune, tags, mirror, all). A plain branch push is a backup and passes.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys

RISKY_LONG = {
    "--tags",
    "--follow-tags",
    "--force",
    "--force-with-lease",
    "--force-if-includes",
    "--mirror",
    "--all",
    "--delete",
    "--prune",
}
# Short options that take a value, so their value letters are not read as flags.
SHORT_WITH_VALUE = {"o"}
WRAPPERS = {"command", "exec", "nohup", "time", "sudo", "nice", "env"}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")
SEPARATORS = set(";&|\n()")
GIT = shutil.which("git") or "/usr/bin/git"


class UnreadableError(Exception):
    pass


def segments(text: str) -> list[list[str]]:
    out: list[list[str]] = [[]]
    for line in text.replace("\\\n", " ").split("\n"):
        out.append([])
        lex = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
        lex.whitespace_split = True
        # A "#" inside a word (feat/issue#12) is not a comment; only a word that
        # starts with "#" opens one, so comments are cut here, not by shlex.
        lex.commenters = ""
        try:
            for tok in lex:
                if tok and set(tok) <= SEPARATORS:
                    out.append([])
                elif tok.startswith("#"):
                    break
                else:
                    out[-1].append(tok)
        except ValueError as exc:
            raise UnreadableError from exc
    return [s for s in out if s]


def strip_prefix(seg: list[str]) -> list[str]:
    i = 0
    while i < len(seg) and (ASSIGNMENT.fullmatch(seg[i]) or os.path.basename(seg[i]) in WRAPPERS):
        i += 1
        while i < len(seg) and seg[i].startswith("-") and os.path.basename(seg[i - 1]) in WRAPPERS:
            i += 1
    rest = seg[i:]
    if rest:
        rest = [os.path.basename(rest[0]), *rest[1:]]
    return rest


def is_tag(ref: str, repo: str) -> bool:
    if ref.startswith("refs/tags/"):
        return True
    if not ref or ref.startswith("refs/") or "/" in ref:
        return False
    found = subprocess.run(  # noqa: S603 - fixed git executable, ref checked as a tag name
        [GIT, "-C", repo, "show-ref", "--verify", "--quiet", f"refs/tags/{ref}"],
        check=False,
    )
    return found.returncode == 0


def risky_push(args: list[str], repo: str) -> bool:
    positional: list[str] = []
    for a in args:
        if a.startswith("--"):
            if a.split("=", 1)[0] in RISKY_LONG:
                return True
            continue
        if a.startswith("-") and len(a) > 1:
            letters = a[1:]
            for ch in letters:
                if ch in SHORT_WITH_VALUE:
                    break
                if ch in "fd":
                    return True
            continue
        positional.append(a)
    refspecs = positional[1:]
    if "tag" in refspecs:
        return True
    for spec in refspecs:
        if spec.startswith("+") or spec.startswith(":"):
            return True
        src, _, dst = spec.partition(":")
        if is_tag(src, repo) or dst.startswith("refs/tags/"):
            return True
    return False


def gated_dirs(text: str, cwd: str) -> list[str]:
    dirs: list[str] = []
    for seg in segments(text):
        words = strip_prefix(seg)
        if not words:
            continue
        if words[0] == "gh":
            rest: list[str] = []
            skip = False
            for w in words[1:]:
                if skip:
                    skip = False
                elif w in ("-R", "--repo"):
                    skip = True
                elif not w.startswith("-"):
                    rest.append(w)
            if rest[:2] == ["pr", "create"]:
                dirs.append(cwd)
            continue
        if words[0] != "git":
            continue
        repo = cwd
        rest = words[1:]
        while rest and rest[0].startswith("-"):
            if rest[0] == "-C" and len(rest) > 1:
                repo = os.path.join(repo, rest[1])
                rest = rest[2:]
            elif rest[0] == "-c":
                rest = rest[2:]
            else:
                rest = rest[1:]
        if rest and rest[0] == "push" and risky_push(rest[1:], repo):
            dirs.append(repo)
    return dirs


MENTIONS = re.compile(r"\bgit\b.*\bpush\b|\bgh\b.*\bpr\b.*\bcreate\b", re.DOTALL)


def main() -> int:
    cwd = os.getcwd()
    text = sys.stdin.read()
    if not MENTIONS.search(text):
        return 1
    try:
        dirs = gated_dirs(text, cwd)
    except UnreadableError:
        dirs = [cwd]
    for d in dict.fromkeys(dirs):
        print(d)
    return 0 if dirs else 1


if __name__ == "__main__":
    sys.exit(main())
