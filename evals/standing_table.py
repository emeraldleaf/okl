#!/usr/bin/env python3
"""Print the evals README's standing table from three probe receipts taken in one sitting.

    PYTHONPATH=src python3 evals/probe_rephrase.py --hybrid off > evals/results/probe-rephrase-<date>-standing-fulltext.txt
    PYTHONPATH=src python3 evals/probe_rephrase.py --hybrid linear > evals/results/probe-rephrase-<date>-standing-linear.txt
    PYTHONPATH=src python3 evals/probe_rephrase.py --hybrid linear --rerank > evals/results/probe-rephrase-<date>-standing-rerank.txt
    python3 evals/standing_table.py <date>

The table is generated, never typed, because a hand-copied figure drifted from its receipt
once (review on #278). It refuses receipts from different commits or stores, since the
columns are a comparison only when the retrieval setting is the one thing that differs.
"""
import ast
import re
import sys
from pathlib import Path

COLUMNS = {"fulltext": "full-text, the default",
           "linear": "with the semantic arm (`--hybrid linear`)",
           "rerank": "with the reranker too (`--rerank`)"}


def _pair(text: str) -> tuple[str, str]:
    """('harness', 'hook') counts from a probe's 'harness N/8, hook M/8' cell."""
    m = re.match(r"harness (\d+)/8, hook (\d+)/8", text)
    if not m:
        sys.exit(f"standing table: unreadable recall cell {text!r}")
    return m.group(1), m.group(2)


def read(path: Path) -> tuple[tuple[str, str, str], dict[str, str]]:
    """The receipt's (store size, commit, vectors) and its table cells."""
    t = path.read_text()
    head = (re.search(r"store: (\d+) nodes", t).group(1), re.search(r"commit (\w+)", t).group(1),
            re.search(r"\((\d+) records with a vector\)", t).group(1))
    own = ast.literal_eval(re.search(r"^recall by variant \(of 8\): (\{.*\})$", t, re.M).group(1))
    held = ast.literal_eval(re.search(r"^held-out recall by variant \(of 8\): (\{.*\})$", t, re.M).group(1))
    rej = re.search(r"^rejection: (\d+) of (\d+) .*counts \[(.*)\]$", t, re.M)
    lat = re.search(r"median (\d+) ms", t)
    if not rej:
        sys.exit(f"standing table: {path} has no rejection line (a probe older than #278)")
    pairs = [_pair(held[k]) for k in ("ticket", "paraphrase", "bug-report")]
    return head, {
        "held_h": " / ".join(h for h, _ in pairs), "held_k": " / ".join(k for _, k in pairs),
        "auth": "{} · {}".format(*_pair(own["authored"])),
        "rej": f"{rej.group(1)} of {rej.group(2)}: {rej.group(3)}",
        "lat": f"{lat.group(1)} ms" if lat else "?",
    }


def main() -> None:
    """Print the table and its provenance note for the receipts of one date."""
    date = sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: standing_table.py <date, as in the receipt names>")
    heads, rows = set(), {}
    for key in COLUMNS:
        head, rows[key] = read(Path(f"evals/results/probe-rephrase-{date}-standing-{key}.txt"))
        heads.add(head)
    if len(heads) != 1:
        sys.exit(f"standing table: the receipts disagree on store or commit, so they are no comparison: {sorted(heads)}")
    store, commit, vectors = heads.pop()

    def line(label: str, field: str) -> str:
        return f"| {label} | " + " | ".join(rows[c][field] for c in COLUMNS) + " |"
    print("| measure (target) | " + " | ".join(COLUMNS.values()) + " |")
    print("|---|" + "---|" * len(COLUMNS))
    print(line("held-out recall, ticket / paraphrase / bug report of 8, harness configuration "
               "(must not fall under a change)", "held_h"))
    print(line("the same, hook configuration: the repo's interests applied, as a live briefing is", "held_k"))
    print(line("authored tasks whose lesson is briefed, of 8, harness · hook (harness stays 8)", "auth"))
    print(line("no-match prompts refused, at most 3 lessons, hook configuration "
               "(must not fall; the counts must not rise)", "rej"))
    print(line("median `core.check`, in-process, model loaded (under 1 s on a laptop)", "lat"))
    print(f"\nReceipts: `probe-rephrase-{date}-standing-{{fulltext,linear,rerank}}.txt`, run in one sitting at\n"
          f"commit {commit} against one {store}-record store ({vectors} with a vector), so the columns differ only\n"
          "in the retrieval setting. The harness configuration applies no interests (what the A/B and\n"
          "pre-flight measure); the hook configuration applies this repo's interests (what a live\n"
          "briefing does), which is why its recall can be lower. Regenerate with `evals/standing_table.py`.")


if __name__ == "__main__":
    main()
