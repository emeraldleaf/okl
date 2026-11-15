#!/usr/bin/env python3
"""REPORT §4bg/§4bh: how often the planned sample would read each contrast right, before any session runs.

docs/EVALUATION.md asks every pre-registration for power from a committed simulation that resamples
earlier receipts. This one draws whole tasks from §4ay's receipt (the only one with the list, the lesson
alone and one at a time on the same tasks) and from §4ax's (two framings of one lesson alone, on the same
tasks), gives each drawn task a true pass rate from a Beta posterior on its counts, simulates the planned
repeats, and reads each contrast the way the pre-registration will: a paired difference in pass rate
averaged over tasks, with a percentile interval from resampling tasks (the unit), never sessions.

    python3 evals/power_4bg.py [--sims 1000] [--receipt]
    python3 evals/power_4bg.py --grown [--sims 1000] [--receipt]   # the two contrasts #457 grows the set for

No model calls. Assumptions it cannot test are stated in the receipt: five earlier tasks stand in for the
spread of fourteen new ones, and a framing that narrows the rule is modelled as a fixed drop per task.

`--grown` sizes the two contrasts the grown task set (§4bg's 14 broken tasks and #457's 29) is for, at 14, 29
and 43 tasks, and writes power-457-<stamp>.json:
  the review after writing against no review, with task profiles from §4az's receipt (none, and the review
      with each lesson checked alone): the review's rate on a task sits a fixed share of the way from none's
      to §4az's (past it when the share is above 1, clipped to [0, 1]), the share set so the mean true gain is
      §4az's bar of 0.25; read on the 95% interval of the paired difference over tasks, above 0;
  Haiku against Sonnet checking one lesson (#456), as non-inferiority: Sonnet's rate per task from §4ay's one
      at a time, Haiku's a fixed amount below it (clipped at 0); not worse when the 90% interval's lower end of
      Haiku minus Sonnet is above -0.15, #456's margin. No Haiku session exists, so power is read when the two
      are equal, and the false alarm when Haiku is worse by exactly the margin on average.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_guard

REPO = Path(__file__).resolve().parents[1]
LIST_RECEIPT = REPO / "evals" / "results" / "replay-list-20261111-0249.json"   # §4ax
ONE_RECEIPT = REPO / "evals" / "results" / "replay-one-20261111-1355.json"     # §4ay
PRIOR_REPEATS = 5        # both receipts ran five repeats a task and arm
SEED, BOOT = 4447, 1000
GAIN, MARGIN, NARROW = 0.25, 0.15, 0.20   # the smallest effects worth acting on, as the pre-registration states them
TASKS = (8, 10, 14)
REPEATS = (2, 3, 5)
REVIEW_RECEIPT = REPO / "evals" / "results" / "review-e2e-20261111-1543.json"   # §4az
REVIEW_GAIN = 0.25       # §4az's bar: the review, each lesson alone, at least 0.25 above no review
CHEAP_MARGIN = 0.15      # #456: Haiku not worse than Sonnet by more than 0.15, on the 90% interval
GROWN_TASKS = (14, 29, 43)          # §4bg's broken tasks, #457's, and both
GROWN_REPEATS = (1, 2, 3, 4, 5)
TARGET_POWER = 0.8       # docs/EVALUATION.md: below it a section is a pilot
CALIBRATION_DRAWS, CALIBRATION_SEED = 20000, 457


def profiles() -> tuple[list[dict], list[dict]]:
    """Per-task pass counts: §4ay's three arms on each task, and §4ax's two framings of one lesson alone."""
    one = json.loads(ONE_RECEIPT.read_text())["per_task"]
    lst = json.loads(LIST_RECEIPT.read_text())["per_task"]
    k = lambda rate: round(rate * PRIOR_REPEATS)  # noqa: E731
    order = [{"alone": k(one["alone_told"][t]), "list": k(one["ten_plain"][t]), "one": k(one["one_at_a_time"][t])}
             for t in sorted(one["alone_told"])]
    framing = [{"a": k(lst["alone_told"][t]), "b": k(lst["alone_plain"][t])} for t in sorted(lst["alone_told"])]
    return order, framing


def true_rate(rng: random.Random, passes: int) -> float:
    """A task's true pass rate, drawn from a Beta posterior on its five sessions (uniform prior), so a task
    that passed 0 of 5 is not taken to be impossible."""
    return rng.betavariate(1 + passes, 1 + PRIOR_REPEATS - passes)


def observed(rng: random.Random, p: float, repeats: int) -> float:
    """The pass rate one task shows over `repeats` sessions."""
    return sum(rng.random() < p for _ in range(repeats)) / repeats


def interval(rng: random.Random, diffs: list[float], level: float) -> tuple[float, float]:
    """Percentile interval of the mean paired difference, resampling tasks."""
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(BOOT))
    lo = means[int((1 - level) / 2 * BOOT)]
    hi = means[min(BOOT - 1, int((1 + level) / 2 * BOOT))]
    return lo, hi


def sim_447(rng: random.Random, order: list[dict], n: int, r: int, delta: float) -> dict[str, float]:
    """One simulated sitting of §4bg. Asking in turn sits `delta` of the way from the list to one at a time
    on every task: 0 is no better than the list, 1 as good as one at a time."""
    d_list, d_one, d_cost, truth = [], [], [], []
    for prof in rng.choices(order, k=n):
        p_alone, p_list, p_one = (true_rate(rng, prof[a]) for a in ("alone", "list", "one"))
        p_turn = p_list + delta * (p_one - p_list)
        truth.append((p_turn - p_list, p_turn - p_one))
        alone, lst, one, turn = (observed(rng, p, r) for p in (p_alone, p_list, p_one, p_turn))
        d_list.append(turn - lst)
        d_one.append(turn - one)
        d_cost.append(alone - lst)
    lo_list, hi_list = interval(rng, d_list, 0.95)
    lo_one90, _ = interval(rng, d_one, 0.90)
    lo_cost, _ = interval(rng, d_cost, 0.95)
    return {"list_costs": lo_cost > 0, "beats_list": lo_list > 0, "small": hi_list < GAIN,
            "not_worse": lo_one90 > -MARGIN,
            "true_gain": sum(t[0] for t in truth) / n, "true_vs_one": sum(t[1] for t in truth) / n}


def sim_450(rng: random.Random, framing: list[dict], n: int, r: int, drop: float) -> dict[str, float]:
    """One simulated sitting of §4bh's main contrast: the lesson framed by its file against the same
    lesson plain. The task-to-task spread of a framing difference comes from §4ax's two framings, whose
    average difference was zero; the file framing then costs `drop` on every task."""
    diffs, truth = [], []
    for prof in rng.choices(framing, k=n):
        p_plain, p_other = true_rate(rng, prof["b"]), true_rate(rng, prof["a"])
        p_file = max(0.0, p_other - drop)
        truth.append(p_file - p_plain)
        diffs.append(observed(rng, p_file, r) - observed(rng, p_plain, r))
    lo, hi = interval(rng, diffs, 0.95)
    return {"narrows": hi < 0, "ruled_out": lo > -NARROW, "true_diff": sum(truth) / n}


def review_profiles() -> list[dict]:
    """Per-task pass counts in §4az: no review, and the review with each lesson checked alone."""
    per = json.loads(REVIEW_RECEIPT.read_text())["per_task"]
    k = lambda rate: round(rate * PRIOR_REPEATS)  # noqa: E731
    return [{"none": k(per["none"][t]), "review": k(per["review_each_alone"][t])} for t in sorted(per["none"])]


def shifted(base: float, other: float, share: float) -> float:
    """`share` of the way from `base` to `other` (past it above 1), kept a probability."""
    return min(1.0, max(0.0, base + share * (other - base)))


def sim_review(rng: random.Random, review: list[dict], n: int, r: int, share: float) -> dict[str, float]:
    """One simulated sitting of the review after writing against no review, on `n` tasks drawn from §4az's."""
    diffs, truth = [], []
    for prof in rng.choices(review, k=n):
        p_none, p_each = true_rate(rng, prof["none"]), true_rate(rng, prof["review"])
        p_review = shifted(p_none, p_each, share)
        truth.append(p_review - p_none)
        diffs.append(observed(rng, p_review, r) - observed(rng, p_none, r))
    lo, _ = interval(rng, diffs, 0.95)
    return {"beats_none": lo > 0, "true_gain": sum(truth) / n}


def sim_cheap(rng: random.Random, order: list[dict], n: int, r: int, drop: float) -> dict[str, float]:
    """One simulated sitting of Haiku against Sonnet checking one lesson, on `n` tasks drawn from §4ay's."""
    diffs, truth = [], []
    for prof in rng.choices(order, k=n):
        p_sonnet = true_rate(rng, prof["one"])
        p_haiku = max(0.0, p_sonnet - drop)
        truth.append(p_haiku - p_sonnet)
        diffs.append(observed(rng, p_haiku, r) - observed(rng, p_sonnet, r))
    lo, _ = interval(rng, diffs, 0.90)
    return {"not_worse": lo > -CHEAP_MARGIN, "true_diff": sum(truth) / n}


def calibrate(effect: Callable[[random.Random, float], float], target: float, hi: float) -> tuple[float, float]:
    """The parameter in [0, hi] at which a task's expected true effect is `target`, by bisection on a fixed
    sample of drawn tasks (the effect rises with the parameter), and the expected effect there."""
    def expected(x: float) -> float:
        rng = random.Random(CALIBRATION_SEED)  # noqa: S311  # NOSONAR - the same draws at every x, on purpose
        return sum(effect(rng, x) for _ in range(CALIBRATION_DRAWS)) / CALIBRATION_DRAWS
    lo = 0.0
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if expected(mid) < target else (lo, mid)
    return (lo + hi) / 2, expected((lo + hi) / 2)


def needed(rows: list[dict], key: str) -> dict[str, int | None]:
    """For each number of tasks, the fewest repeats whose power reaches TARGET_POWER, or None."""
    out: dict[str, int | None] = {}
    for n in GROWN_TASKS:
        enough = [x["repeats"] for x in rows if x["tasks"] == n and x[key] >= TARGET_POWER]
        out[str(n)] = min(enough) if enough else None
    return out


def main_grown(sims: int, write: bool) -> int:
    """The review against no review and Haiku against Sonnet, at each size of the grown set."""
    run = run_guard.start()
    review = review_profiles()
    order, _ = profiles()

    def gain_at(rng: random.Random, share: float) -> float:
        prof = rng.choice(review)
        p_none = true_rate(rng, prof["none"])
        return shifted(p_none, true_rate(rng, prof["review"]), share) - p_none

    def fall_at(rng: random.Random, drop: float) -> float:
        p_sonnet = true_rate(rng, rng.choice(order)["one"])
        return p_sonnet - max(0.0, p_sonnet - drop)

    share_gain, gain_reached = calibrate(gain_at, REVIEW_GAIN, 20.0)
    _, gain_as_seen = calibrate(lambda rng, _x: gain_at(rng, 1.0), 0.0, 1.0)
    drop_margin, fall_reached = calibrate(fall_at, CHEAP_MARGIN, 1.0)
    rng = random.Random(SEED)  # noqa: S311  # NOSONAR - a seeded simulation, reproducible on purpose
    out_review, out_cheap = [], []
    for n in GROWN_TASKS:
        for r in GROWN_REPEATS:
            at_gain = [sim_review(rng, review, n, r, share_gain) for _ in range(sims)]
            as_seen = [sim_review(rng, review, n, r, 1.0) for _ in range(sims)]
            null = [sim_review(rng, review, n, r, 0.0) for _ in range(sims)]
            out_review.append({"tasks": n, "repeats": r, "beats_none_at_gain": rate(at_gain, "beats_none"),
                               "beats_none_as_seen": rate(as_seen, "beats_none"),
                               "beats_none_false_alarm": rate(null, "beats_none"),
                               "true_gain_at_gain": rate(at_gain, "true_gain"),
                               "true_gain_as_seen": rate(as_seen, "true_gain")})
            equal = [sim_cheap(rng, order, n, r, 0.0) for _ in range(sims)]
            edge = [sim_cheap(rng, order, n, r, drop_margin) for _ in range(sims)]
            out_cheap.append({"tasks": n, "repeats": r, "not_worse_when_equal": rate(equal, "not_worse"),
                              "not_worse_false_alarm_at_margin": rate(edge, "not_worse"),
                              "true_diff_at_margin": rate(edge, "true_diff")})
            print(f"n={n} r={r}  review: {out_review[-1]}\n          cheap: {out_cheap[-1]}", flush=True)
    receipt = run.stamp({
        "section": "#457 power: the review against none, Haiku against Sonnet",
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": [REVIEW_RECEIPT.name, ONE_RECEIPT.name], "sims": sims, "bootstrap": BOOT, "seed": SEED,
        "review_gain": REVIEW_GAIN, "cheap_margin": CHEAP_MARGIN, "target_power": TARGET_POWER,
        "review_share_at_gain": round(share_gain, 3), "review_true_gain_at_share": round(gain_reached, 3),
        "review_true_gain_as_seen": round(gain_as_seen, 3),
        "cheap_drop_at_margin": round(drop_margin, 3), "cheap_true_fall_at_drop": round(fall_reached, 3),
        "assumptions": [
            "the five tasks of 4az stand in for the spread of the review's gain over the new tasks",
            "the five tasks of 4ay's one at a time stand in for Sonnet's rate checking one lesson on them",
            "a task's true rate is a Beta(1+k, 1+5-k) draw from its five earlier sessions",
            "the review's rate sits a fixed share of the way from none's to 4az's each-alone rate on every task, "
            "clipped to [0, 1]; the share is set so the mean true gain is the bar",
            "Haiku's rate is Sonnet's less a fixed amount on every task, clipped at 0; no Haiku session exists",
            "the unit is the task: paired differences averaged over tasks, percentile intervals from resampling "
            "tasks"],
        "power_review": out_review, "power_cheap": out_cheap,
        "repeats_needed": {"review_beats_none_at_gain": needed(out_review, "beats_none_at_gain"),
                           "haiku_not_worse_when_equal": needed(out_cheap, "not_worse_when_equal")},
    })
    if write:
        path = REPO / "evals" / "results" / f"power-457-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.json"
        path.write_text(json.dumps(receipt, indent=1) + "\n")
        print(f"receipt: {path.relative_to(REPO)}")
    return 0


def rate(results: list[dict], key: str) -> float:
    """The share of simulated sittings that read `key`, or the mean of a number they carry."""
    return round(sum(x[key] for x in results) / len(results), 3)


def main() -> int:
    """Every planned size, each scenario `--sims` times; the receipt with --receipt."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sims", type=int, default=1000)
    ap.add_argument("--receipt", action="store_true")
    ap.add_argument("--grown", action="store_true",
                    help="instead: the review against none and Haiku against Sonnet, at the grown set's sizes")
    args = ap.parse_args()
    if args.grown:
        return main_grown(args.sims, args.receipt)
    run = run_guard.start()
    order, framing = profiles()
    rng = random.Random(SEED)  # noqa: S311  # NOSONAR - a seeded simulation, reproducible on purpose
    # Mean gain of asking in turn over the list, at delta: delta * mean(one - list), taken on the
    # posterior means (1 + k) / (2 + 5) the draws centre on, not the raw rates, which sit further apart.
    span = sum((p["one"] - p["list"]) / (PRIOR_REPEATS + 2) for p in order) / len(order)
    delta_gain = min(1.0, GAIN / span)
    delta_margin = max(0.0, 1 - MARGIN / span)   # asking in turn MARGIN short of one at a time, on average
    out_447, out_450 = [], []
    for n in TASKS:
        for r in REPEATS:
            null = [sim_447(rng, order, n, r, 0.0) for _ in range(args.sims)]
            gain = [sim_447(rng, order, n, r, delta_gain) for _ in range(args.sims)]
            same = [sim_447(rng, order, n, r, 1.0) for _ in range(args.sims)]
            edge = [sim_447(rng, order, n, r, delta_margin) for _ in range(args.sims)]
            out_447.append({"tasks": n, "repeats": r,
                            "list_costs": rate(same, "list_costs"),
                            "beats_list_at_gain": rate(gain, "beats_list"),
                            "beats_list_when_equal_to_one": rate(same, "beats_list"),
                            "beats_list_false_alarm": rate(null, "beats_list"),
                            "not_worse_when_equal": rate(same, "not_worse"),
                            "not_worse_false_alarm_at_margin": rate(edge, "not_worse"),
                            "true_gain_at_gain": rate(gain, "true_gain"),
                            "true_vs_one_at_margin": rate(edge, "true_vs_one")})
            drop = [sim_450(rng, framing, n, r, NARROW) for _ in range(args.sims)]
            none = [sim_450(rng, framing, n, r, 0.0) for _ in range(args.sims)]
            out_450.append({"tasks": n, "repeats": r,
                            "narrows_at_drop": rate(drop, "narrows"),
                            "narrows_false_alarm": rate(none, "narrows"),
                            "ruled_out_when_none": rate(none, "ruled_out"),
                            "true_diff_at_drop": rate(drop, "true_diff"),
                            "true_diff_when_none": rate(none, "true_diff")})
            print(f"n={n} r={r}  447: {out_447[-1]}\n          450: {out_450[-1]}", flush=True)
    receipt = {
        "section": "4bg/4bh power", "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sources": [LIST_RECEIPT.name, ONE_RECEIPT.name], "sims": args.sims, "bootstrap": BOOT, "seed": SEED,
        "gain": GAIN, "margin": MARGIN, "narrow": NARROW, "delta_at_gain": round(delta_gain, 3),
        "delta_at_margin": round(delta_margin, 3),
        "one_minus_list_on_4ay": round(span, 3),
        "assumptions": ["the five tasks of 4ax/4ay stand in for the spread of the new tasks",
                        "a task's true rate is a Beta(1+k, 1+5-k) draw from its five earlier sessions",
                        "asking in turn sits a fixed share of the way from the list to one at a time on every task",
                        "a file framing that narrows costs the same on every task, on top of 4ax's framing spread"],
        "power_447": out_447, "power_450": out_450,
    }
    receipt = run.stamp(receipt)
    if args.receipt:
        path = REPO / "evals" / "results" / f"power-4bg-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.json"
        path.write_text(json.dumps(receipt, indent=1) + "\n")
        print(f"receipt: {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
