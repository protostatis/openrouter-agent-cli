#!/usr/bin/env python3
"""Simulate power for the paired completion-policy campaign.

The unit of independent evidence is a task.  Each task receives the same
number of unassisted/policy pairs.  The simulation samples the four possible
paired outcomes (both pass, policy-only pass, unassisted-only pass, and both
fail), then uses a task-level 95% t interval for the mean policy-minus-
unassisted difference.

This is deliberately a planning tool, not an analysis of campaign results.
Its assumptions and seed are printed with the results so the table can be
reproduced and challenged before the campaign is frozen.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from statistics import mean


Z95 = 1.959963984540054

# Two-sided 95% t critical values for the task counts used in the plan.
T95_BY_TASKS = {20: 2.093024, 30: 2.04523, 40: 2.022691}


def beta_shape_for_mean_half(sd: float) -> float:
    """Return the equal beta-shape parameter for mean .5 and ``sd``."""
    if not 0 < sd < 0.5:
        raise ValueError("baseline SD must be between 0 and 0.5")
    return (1 / (4 * sd * sd) - 1) / 2


def t95(n_tasks: int) -> float:
    if n_tasks in T95_BY_TASKS:
        return T95_BY_TASKS[n_tasks]
    df = n_tasks - 1
    if df <= 0:
        raise ValueError("task count must be at least 2")
    # Cornish-Fisher approximation, sufficient for planning outside the
    # explicitly tabulated 20/30/40-task designs.
    z = Z95
    return (
        z
        + (z**3 + z) / (4 * df)
        + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * df**2)
        + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / (384 * df**3)
    )


def paired_probabilities(p: float, difference: float, discordance: float) -> tuple[float, ...]:
    """Return probabilities for (both, policy-only, baseline-only, neither).

    ``discordance`` is clamped to the feasible range for the two marginal
    pass probabilities.  The resulting joint distribution has baseline pass
    probability ``p`` and policy pass probability ``p + difference``.
    """
    q = p + difference
    if not 0 <= p <= 1 or not 0 <= q <= 1:
        raise ValueError("marginal probabilities must be in [0, 1]")
    minimum = abs(difference)
    maximum = min(p + q, 2 - p - q)
    c = min(max(discordance, minimum), maximum)
    policy_only = (c + difference) / 2
    baseline_only = (c - difference) / 2
    both = (p + q - c) / 2
    neither = 1 - both - policy_only - baseline_only
    return both, policy_only, baseline_only, neither


def draw_task(
    rng: random.Random,
    *,
    baseline_sd: float,
    effect_mean: float,
    effect_sd: float,
    discordance: float,
    repeats: int,
) -> tuple[float, int, int]:
    """Simulate one task and return (difference, baseline passes, harms)."""
    alpha = beta_shape_for_mean_half(baseline_sd)
    # Retry boundary-incompatible latent values instead of silently clipping
    # them, which would distort the requested effect distribution.
    for _ in range(10_000):
        baseline_probability = rng.betavariate(alpha, alpha)
        difference = rng.gauss(effect_mean, effect_sd)
        if 0 <= baseline_probability + difference <= 1:
            break
    else:
        raise RuntimeError("could not draw a feasible task")

    both, policy_only, baseline_only, neither = paired_probabilities(
        baseline_probability, difference, discordance
    )
    cumulative = (both, both + policy_only, both + policy_only + baseline_only)
    baseline_passes = 0
    harms = 0
    task_difference = 0
    for _ in range(repeats):
        draw = rng.random()
        if draw < cumulative[0]:
            baseline_passes += 1
        elif draw < cumulative[1]:
            task_difference += 1
        elif draw < cumulative[2]:
            baseline_passes += 1
            harms += 1
            task_difference -= 1
        else:
            pass
    return task_difference / repeats, baseline_passes, harms


def simulate_design(
    *,
    n_tasks: int,
    repeats: int,
    effect_mean: float,
    effect_sd: float,
    baseline_sd: float,
    discordance: float,
    simulations: int,
    seed: int,
) -> dict[str, float | int]:
    rng = random.Random(seed)
    detections = 0
    regression_ok = 0
    complete_rule = 0
    false_promotions = 0
    for _ in range(simulations):
        differences: list[float] = []
        total_baseline_passes = 0
        total_harms = 0
        for _ in range(n_tasks):
            difference, baseline_passes, harms = draw_task(
                rng,
                baseline_sd=baseline_sd,
                effect_mean=effect_mean,
                effect_sd=effect_sd,
                discordance=discordance,
                repeats=repeats,
            )
            differences.append(difference)
            total_baseline_passes += baseline_passes
            total_harms += harms

        estimate = mean(differences)
        standard_error = math.sqrt(
            sum((value - estimate) ** 2 for value in differences) / (n_tasks - 1)
        ) / math.sqrt(n_tasks)
        lower = estimate - t95(n_tasks) * standard_error
        detected = estimate >= 0.10 and lower > 0
        detections += detected
        if effect_mean == 0 and detected:
            false_promotions += 1

        # This treats a "baseline-passing task turning into failure" as a
        # paired baseline-pass attempt that is a policy failure.  The rule is
        # still subject to explicit freezing before campaign results exist.
        regression_rate = total_harms / total_baseline_passes if total_baseline_passes else 0
        regression_passes = regression_rate <= 0.05
        regression_ok += regression_passes
        complete_rule += detected and regression_passes

    return {
        "tasks": n_tasks,
        "repeats_per_arm": repeats,
        "final_attempts": n_tasks * repeats * 2,
        "true_effect": effect_mean,
        "effect_sd": effect_sd,
        "baseline_sd": baseline_sd,
        "discordance": discordance,
        "simulations": simulations,
        "detection_power": detections / simulations,
        "regression_guardrail_probability": regression_ok / simulations,
        "complete_rule_probability": complete_rule / simulations,
        "false_promotion_probability": false_promotions / simulations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="20,30,40", help="comma-separated task counts")
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--simulations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260906)
    parser.add_argument("--effect-sd", type=float, default=0.15)
    parser.add_argument("--baseline-sd", type=float, default=0.25)
    parser.add_argument("--discordance", type=float, default=0.15)
    args = parser.parse_args()
    if args.repeats <= 0 or args.simulations <= 0:
        parser.error("repeats and simulations must be positive")
    task_counts = [int(value) for value in args.tasks.split(",") if value]
    effects = (0.0, 0.10, 0.15, 0.20)
    rows = []
    for tasks in task_counts:
        for effect in effects:
            rows.append(
                simulate_design(
                    n_tasks=tasks,
                    repeats=args.repeats,
                    effect_mean=effect,
                    effect_sd=args.effect_sd,
                    baseline_sd=args.baseline_sd,
                    discordance=args.discordance,
                    simulations=args.simulations,
                    seed=args.seed + tasks * 1000 + round(effect * 100),
                )
            )
    print(
        json.dumps(
            {
                "assumptions": {
                    "baseline_mean": 0.5,
                    "paired_analysis": "task-level mean difference with two-sided 95% t interval",
                    "detection_rule": "estimated effect >= 0.10 and lower CI > 0",
                    "baseline_probability_distribution": "Beta(alpha, alpha)",
                    "seed": args.seed,
                },
                "results": rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
