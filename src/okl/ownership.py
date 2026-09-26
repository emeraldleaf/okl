"""Which files in someone else's repo are okl's, and whether they are still untouched (#49).

okl writes into other people's repositories: two hook scripts and a CI workflow. It used
to overwrite the hooks on every `okl init`, silently discarding a local edit, and there
was no uninstall -- removing okl meant hand-editing settings next to other tools' hooks.

Each okl-owned file carries one line, `# okl-fingerprint: sha256:<hex>`, the hash of the
file with that line removed. A file whose hash still matches is an unmodified okl file of
ANY version, so it is safe to upgrade or remove; a mismatch means someone edited it, and
okl keeps it. The check needs no local state, so it works the same for a teammate who
cloned the repo as for whoever ran `okl init`.

After editing an okl-owned file in this repo, re-stamp it:
    python -m okl.ownership --stamp <file>...
tests/test_scaffold.py fails, naming the correct value, when a stamp is stale.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

PREFIX = "# okl-fingerprint: sha256:"
_LINE = re.compile(r"^# okl-fingerprint: sha256:[0-9a-f]*\n", re.MULTILINE)

OKL = "okl"                 # an unmodified okl file: upgrade or remove freely
MODIFIED = "modified"       # carries a fingerprint that no longer matches: someone edited it
UNKNOWN = "unknown"         # no fingerprint: a pre-0.7 okl file, or not okl's at all
MISSING = "missing"


def body(text: str) -> str:
    """The file with its fingerprint line removed -- what the fingerprint covers."""
    return _LINE.sub("", text, count=1)


def digest(text: str) -> str:
    return hashlib.sha256(body(text).encode("utf-8")).hexdigest()


def stamp(text: str) -> str:
    """Return `text` carrying a correct fingerprint line: after a shebang, else first."""
    clean = body(text)
    line = f"{PREFIX}{hashlib.sha256(clean.encode('utf-8')).hexdigest()}\n"
    if clean.startswith("#!"):
        first, _, rest = clean.partition("\n")
        return f"{first}\n{line}{rest}"
    return line + clean


def embedded(text: str) -> str | None:
    m = re.search(r"^# okl-fingerprint: sha256:([0-9a-f]+)$", text, re.MULTILINE)
    return m.group(1) if m else None


def status(path: Path, shipped: str) -> str:
    """Classify an installed file against okl's ownership rules.

    `shipped` is the version this okl would install. A file with no fingerprint that is
    byte-identical to that version's body is still okl's -- that is how files installed
    before fingerprints existed are recognised when they were never edited.
    """
    if not path.exists():
        return MISSING
    text = path.read_text(encoding="utf-8")
    mark = embedded(text)
    if mark is None:
        return OKL if text == body(shipped) else UNKNOWN
    return OKL if mark == digest(text) else MODIFIED


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[0] != "--stamp":
        print("usage: python -m okl.ownership --stamp <file>...", file=sys.stderr)
        return 2
    for name in argv[1:]:
        p = Path(name)
        p.write_text(stamp(p.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"stamped {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
