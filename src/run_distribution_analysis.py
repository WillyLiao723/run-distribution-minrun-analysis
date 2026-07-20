"""Run-distribution analysis for Timsort-style and Powersort-style policies.

Research question
-----------------
Which run-distribution features amplify or weaken the normalized merge-cost
reduction of a Powersort-style policy relative to a Timsort-style policy, and
how does minrun preprocessing change that relationship?

The program intentionally measures merge-tree structure rather than wall-clock
runtime. It produces the CSV files, figures, and Mermaid merge trees used by the
report.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

import matplotlib.pyplot as plt
import pandas as pd


# =============================================================================
# 0. Configuration
# =============================================================================

RANDOM_SEED = 42
DEFAULT_SIZES = (1000, 5000, 10000)
DEFAULT_TRIALS = 5

# =============================================================================
# 1. Core data structures
# =============================================================================

@dataclass
class SortStats:

    minrun: int = 0
    insertion_elements: int = 0
    extended_run_count: int = 0

    merge_comparisons: int = 0
    weighted_merge_workload: int = 0

    adjusted_runs: list[tuple[int, int]] = field(default_factory=list)
    merge_history: list[dict[str, int | tuple[int, int]]] = field(
        default_factory=list
    )


@dataclass
class Run:
    start: int
    end: int
    power: int = -1
    height: int = 0

    @property
    def length(self) -> int:
        return self.end - self.start


Algorithm = Callable[[Sequence[int]], tuple[list[int], SortStats]]
Generator = Callable[[int, random.Random], list[int]]


# =============================================================================
# 2. General utilities and run features
# =============================================================================


def safe_divide(numerator: float, denominator: float, *, eps: float = 1e-12) -> float:
    """Return NaN when a ratio is undefined or numerically unstable."""

    if pd.isna(numerator) or pd.isna(denominator) or abs(denominator) <= eps:
        return math.nan
    return numerator / denominator


def verify_sorted(original: Sequence[int], result: Sequence[int]) -> bool:
    return list(result) == sorted(original)


def calc_minrun(n: int) -> int:
    """Compute the standard Timsort-style minrun value."""

    if n < 0:
        raise ValueError("n must be non-negative")

    remainder = 0
    while n >= 64:
        remainder |= n & 1
        n >>= 1
    return n + remainder


def run_lengths_from_runs(runs: Iterable[tuple[int, int]]) -> list[int]:
    return [right - left for left, right in runs]


def compute_run_entropy(runs: Iterable[tuple[int, int]], n: int) -> tuple[float, float]:
    """Return run entropy H and its scaled value nH."""

    if n <= 0:
        return 0.0, 0.0

    entropy = 0.0
    for left, right in runs:
        length = right - left
        if length <= 0:
            continue
        probability = length / n
        entropy += probability * math.log2(n / length)

    return entropy, n * entropy


def summarize_run_lengths(
    runs: Iterable[tuple[int, int]],
    n: int,
    prefix: str,
) -> dict[str, float | int]:
    """Compute the structural features used in the report."""

    lengths = run_lengths_from_runs(runs)
    entropy, entropy_nh = compute_run_entropy(
        ((0, length) for length in lengths), n
    )

    if not lengths:
        return {
            f"{prefix}_run_count": 0,
            f"{prefix}_normalized_run_count": 0.0,
            f"{prefix}_avg_run_length": 0.0,
            f"{prefix}_run_cv": 0.0,
            f"{prefix}_max_run_ratio": 0.0,
            f"{prefix}_max_to_avg_ratio": 0.0,
            f"{prefix}_run_entropy": 0.0,
            f"{prefix}_run_entropy_bound_nH": 0.0,
        }

    count = len(lengths)
    average = sum(lengths) / count
    variance = sum((length - average) ** 2 for length in lengths) / count
    standard_deviation = math.sqrt(variance)
    maximum = max(lengths)

    return {
        f"{prefix}_run_count": count,
        f"{prefix}_normalized_run_count": safe_divide(count, n),
        f"{prefix}_avg_run_length": average,
        f"{prefix}_run_cv": safe_divide(standard_deviation, average),
        f"{prefix}_max_run_ratio": safe_divide(maximum, n),
        f"{prefix}_max_to_avg_ratio": safe_divide(maximum, average),
        f"{prefix}_run_entropy": entropy,
        f"{prefix}_run_entropy_bound_nH": entropy_nh,
    }


def detect_natural_runs_without_modifying(
    values: Sequence[int],
) -> list[tuple[int, int]]:
    """Detect maximal ascending or strictly descending natural runs."""

    n = len(values)
    runs: list[tuple[int, int]] = []
    start = 0

    while start < n:
        if start == n - 1:
            end = n
        elif values[start + 1] < values[start]:
            end = start + 2
            while end < n and values[end] < values[end - 1]:
                end += 1
        else:
            end = start + 2
            while end < n and values[end - 1] <= values[end]:
                end += 1

        runs.append((start, end))
        start = end

    return runs


def analyze_natural_runs(values: Sequence[int]) -> dict[str, float | int]:
    runs = detect_natural_runs_without_modifying(values)
    return summarize_run_lengths(runs, len(values), "natural")


# =============================================================================
# 3. Run detection and minrun preprocessing
# =============================================================================


def reverse_slice(values: list[int], left: int, right_inclusive: int) -> None:
    while left < right_inclusive:
        values[left], values[right_inclusive] = (
            values[right_inclusive],
            values[left],
        )
        left += 1
        right_inclusive -= 1


def count_run_and_make_ascending(values: list[int], start: int) -> int:
    """Return the exclusive end of one natural run and reverse it if needed."""

    n = len(values)
    if start >= n - 1:
        return n

    end = start + 2

    if values[start + 1] < values[start]:
        while end < n and values[end] < values[end - 1]:
            end += 1
        reverse_slice(values, start, end - 1)
    else:
        while end < n and values[end - 1] <= values[end]:
            end += 1

    return end


def binary_insertion_sort(values: list[int], left: int, right: int) -> None:
    """Stably sort values[left:right] for minrun extension."""

    for index in range(left + 1, right):
        key = values[index]
        low = left
        high = index

        while low < high:
            middle = (low + high) // 2
            if key < values[middle]:
                high = middle
            else:
                low = middle + 1

        position = index
        while position > low:
            values[position] = values[position - 1]
            position -= 1
        values[low] = key


def build_runs_without_minrun(
    values: list[int], stats: SortStats
) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start = 0

    while start < len(values):
        end = count_run_and_make_ascending(values, start)
        runs.append((start, end))
        start = end

    stats.adjusted_runs = runs.copy()
    return runs


def build_runs_with_minrun(
    values: list[int], stats: SortStats
) -> list[tuple[int, int]]:
    n = len(values)
    minrun = calc_minrun(n)
    stats.minrun = minrun

    runs: list[tuple[int, int]] = []
    start = 0

    while start < n:
        natural_end = count_run_and_make_ascending(values, start)
        natural_length = natural_end - start
        end = natural_end

        if natural_length < minrun:
            end = min(n, start + minrun)
            binary_insertion_sort(values, start, end)
            stats.insertion_elements += end - start
            stats.extended_run_count += 1

        runs.append((start, end))
        start = end

    stats.adjusted_runs = runs.copy()
    return runs


# =============================================================================
# 4. Stable merge and merge-tree accounting
# =============================================================================


def merge(
    values: list[int],
    left: int,
    middle: int,
    right: int,
    stats: SortStats,
) -> None:
    buffer: list[int] = []
    i = left
    j = middle

    while i < middle and j < right:
        stats.merge_comparisons += 1
        if values[i] <= values[j]:
            buffer.append(values[i])
            i += 1
        else:
            buffer.append(values[j])
            j += 1

    buffer.extend(values[i:middle])
    buffer.extend(values[j:right])
    values[left:right] = buffer


def merge_stack_at(
    values: list[int], stack: list[Run], index: int, stats: SortStats
) -> None:
    left_run = stack[index]
    right_run = stack[index + 1]

    if left_run.end != right_run.start:
        raise AssertionError("Only adjacent runs may be merged")

    left = left_run.start
    middle = left_run.end
    right = right_run.end
    merged_height = max(left_run.height, right_run.height) + 1

    merge(values, left, middle, right, stats)

    merged_length = right - left
    stats.weighted_merge_workload += merged_length
    stats.merge_history.append(
        {
            "left": (left_run.start, left_run.end),
            "right": (right_run.start, right_run.end),
            "merged": (left_run.start, right_run.end),
            "left_len": left_run.length,
            "right_len": right_run.length,
            "merged_len": merged_length,
            "height": merged_height,
        }
    )

    stack[index] = Run(
        start=left_run.start,
        end=right_run.end,
        power=left_run.power,
        height=merged_height,
    )
    del stack[index + 1]


# =============================================================================
# 5. Powersort-style merge policy
# =============================================================================


def node_power(left: int, middle: int, right: int, n: int) -> int:
    """Return the first binary partition level separating adjacent run centers."""

    if n <= 0:
        return 0

    left_center_numerator = left + middle
    right_center_numerator = middle + right
    denominator = 2 * n
    power = 0

    while True:
        left_bucket = (left_center_numerator << power) // denominator
        right_bucket = (right_center_numerator << power) // denominator
        if left_bucket != right_bucket:
            return power
        power += 1


def powersort_merge_from_runs(
    values: list[int], runs: Sequence[tuple[int, int]], stats: SortStats
) -> None:
    if not runs:
        return

    n = len(values)
    first_left, first_right = runs[0]
    stack = [Run(first_left, first_right)]

    for left, right in runs[1:]:
        top = stack[-1]
        new_power = node_power(top.start, top.end, right, n)

        while len(stack) >= 2 and stack[-1].power > new_power:
            merge_stack_at(values, stack, len(stack) - 2, stats)

        stack.append(Run(left, right, power=new_power))

    while len(stack) > 1:
        merge_stack_at(values, stack, len(stack) - 2, stats)


# =============================================================================
# 6. Timsort-style merge policy
# =============================================================================


def timsort_merge_collapse(
    values: list[int], stack: list[Run], stats: SortStats
) -> None:
    """Apply corrected Timsort-style stack invariants."""

    while len(stack) > 1:
        index = len(stack) - 2

        violates_upper_invariant = (
            index > 0
            and stack[index - 1].length
            <= stack[index].length + stack[index + 1].length
        )
        violates_deeper_invariant = (
            index > 1
            and stack[index - 2].length
            <= stack[index - 1].length + stack[index].length
        )

        if violates_upper_invariant or violates_deeper_invariant:
            if index > 0 and stack[index - 1].length < stack[index + 1].length:
                index -= 1
            merge_stack_at(values, stack, index, stats)
        elif stack[index].length <= stack[index + 1].length:
            merge_stack_at(values, stack, index, stats)
        else:
            break


def timsort_merge_from_runs(
    values: list[int], runs: Sequence[tuple[int, int]], stats: SortStats
) -> None:
    stack: list[Run] = []

    for left, right in runs:
        stack.append(Run(left, right))
        timsort_merge_collapse(values, stack, stats)

    while len(stack) > 1:
        index = len(stack) - 2
        if index > 0 and stack[index - 1].length < stack[index + 1].length:
            index -= 1
        merge_stack_at(values, stack, index, stats)


# =============================================================================
# 7. Four experimental conditions
# =============================================================================


def run_merge_policy(
    original: Sequence[int], *, policy: str, use_minrun: bool
) -> tuple[list[int], SortStats]:
    values = list(original)
    stats = SortStats()

    if len(values) <= 1:
        stats.adjusted_runs = [(0, len(values))] if values else []
        return values, stats

    if use_minrun:
        runs = build_runs_with_minrun(values, stats)
    else:
        runs = build_runs_without_minrun(values, stats)

    if policy == "timsort":
        timsort_merge_from_runs(values, runs, stats)
    elif policy == "powersort":
        powersort_merge_from_runs(values, runs, stats)
    else:
        raise ValueError(f"Unknown merge policy: {policy}")

    return values, stats


def timsort_style_with_minrun(values: Sequence[int]) -> tuple[list[int], SortStats]:
    return run_merge_policy(values, policy="timsort", use_minrun=True)


def powersort_style_with_minrun(values: Sequence[int]) -> tuple[list[int], SortStats]:
    return run_merge_policy(values, policy="powersort", use_minrun=True)


def timsort_style_without_minrun(values: Sequence[int]) -> tuple[list[int], SortStats]:
    return run_merge_policy(values, policy="timsort", use_minrun=False)


def powersort_style_without_minrun(values: Sequence[int]) -> tuple[list[int], SortStats]:
    return run_merge_policy(values, policy="powersort", use_minrun=False)


ALGORITHMS: dict[str, Algorithm] = {
    "timsort_style_with_minrun": timsort_style_with_minrun,
    "powersort_style_with_minrun": powersort_style_with_minrun,
    "timsort_style_without_minrun": timsort_style_without_minrun,
    "powersort_style_without_minrun": powersort_style_without_minrun,
}


# =============================================================================
# 8. Synthetic run-distribution generators
# =============================================================================


def make_array_from_run_lengths(lengths: Sequence[int]) -> list[int]:
    """Create exactly the requested ascending natural-run lengths."""

    if any(length <= 0 for length in lengths):
        raise ValueError("Every run length must be positive")

    total = sum(lengths)
    spacing = total + 1
    run_count = len(lengths)
    result: list[int] = []

    for index, length in enumerate(lengths):
        start_value = (run_count - index) * spacing
        result.extend(range(start_value, start_value + length))

    return result


def scaled_lengths(pattern: Sequence[int], n: int) -> list[int]:
    """Scale a positive pattern to integer lengths that sum exactly to n."""

    if n <= 0:
        return []
    if not pattern or any(weight <= 0 for weight in pattern):
        raise ValueError("pattern must contain positive values")

    active_pattern = list(pattern[: min(len(pattern), n)])
    total_weight = sum(active_pattern)
    ideal = [n * weight / total_weight for weight in active_pattern]
    lengths = [max(1, math.floor(value)) for value in ideal]

    difference = n - sum(lengths)

    if difference > 0:
        order = sorted(
            range(len(lengths)),
            key=lambda i: ideal[i] - math.floor(ideal[i]),
            reverse=True,
        )
        for index in range(difference):
            lengths[order[index % len(order)]] += 1
    elif difference < 0:
        order = sorted(range(len(lengths)), key=lambda i: lengths[i], reverse=True)
        cursor = 0
        while difference < 0:
            target = order[cursor % len(order)]
            if lengths[target] > 1:
                lengths[target] -= 1
                difference += 1
            cursor += 1

    if sum(lengths) != n:
        raise AssertionError("scaled_lengths failed to preserve the requested size")

    return lengths


def repeated_pattern_lengths(
    pattern: Sequence[int], n: int, *, min_tail: int = 1
) -> list[int]:
    if n <= 0:
        return []
    if not pattern or any(length <= 0 for length in pattern):
        raise ValueError("pattern must contain positive lengths")

    lengths: list[int] = []
    remaining = n
    index = 0

    while remaining > 0:
        length = min(pattern[index % len(pattern)], remaining)
        if 0 < remaining - length < min_tail:
            length = remaining
        lengths.append(length)
        remaining -= length
        index += 1

    return lengths


def gen_random(n: int, rng: random.Random) -> list[int]:
    return [rng.randint(0, n) for _ in range(n)]


def gen_nearly_sorted(n: int, rng: random.Random) -> list[int]:
    values = list(range(n))
    if n < 2:
        return values

    swaps = max(1, int(n * 0.02))
    for _ in range(swaps):
        i = rng.randrange(n)
        j = rng.randrange(n)
        values[i], values[j] = values[j], values[i]
    return values


def gen_balanced_runs(n: int, rng: random.Random) -> list[int]:
    del rng
    return make_array_from_run_lengths(scaled_lengths([1] * 8, n))


def gen_skewed_runs(n: int, rng: random.Random) -> list[int]:
    del rng
    return make_array_from_run_lengths(scaled_lengths([16, 1, 1, 1, 1, 1, 1, 1], n))


def gen_exponential_runs(n: int, rng: random.Random) -> list[int]:
    del rng
    return make_array_from_run_lengths(scaled_lengths([1, 2, 4, 8, 16, 32], n))


def gen_many_tiny_runs(n: int, rng: random.Random) -> list[int]:
    del rng
    lengths = [2] * (n // 2)
    if n % 2:
        lengths.append(1)
    return make_array_from_run_lengths(lengths)


def gen_duplicate_heavy(n: int, rng: random.Random) -> list[int]:
    return [rng.randint(0, 9) for _ in range(n)]


def gen_alternating_small_large_raw_runs(n: int, rng: random.Random) -> list[int]:
    del rng
    return make_array_from_run_lengths(
        repeated_pattern_lengths([2, 64], n)
    )


def gen_alternating_minrun_large_runs(n: int, rng: random.Random) -> list[int]:
    del rng
    minrun = calc_minrun(n)
    return make_array_from_run_lengths(
        repeated_pattern_lengths([minrun, 4 * minrun], n, min_tail=minrun)
    )


def gen_one_huge_tail_raw_runs(n: int, rng: random.Random) -> list[int]:
    del rng
    if n <= 1:
        return list(range(n))

    tiny_total = max(1, n // 5)
    tiny_lengths = [2] * (tiny_total // 2)
    if tiny_total % 2:
        tiny_lengths.append(1)
    tail = n - sum(tiny_lengths)
    return make_array_from_run_lengths(tiny_lengths + ([tail] if tail else []))


def gen_one_huge_tail_minrun_aware(n: int, rng: random.Random) -> list[int]:
    del rng
    minrun = calc_minrun(n)

    if n <= 6 * minrun:
        lengths = repeated_pattern_lengths(
            [minrun, minrun, 4 * minrun], n, min_tail=minrun
        )
    else:
        prefix = [minrun] * 5
        lengths = prefix + [n - sum(prefix)]

    return make_array_from_run_lengths(lengths)


def gen_near_minrun_boundary(n: int, rng: random.Random) -> list[int]:
    del rng
    minrun = calc_minrun(n)
    return make_array_from_run_lengths(
        repeated_pattern_lengths(
            [max(1, minrun - 1), minrun + 1], n
        )
    )


DATA_GENERATORS: dict[str, Generator] = {
    "random": gen_random,
    "nearly_sorted": gen_nearly_sorted,
    "balanced_runs": gen_balanced_runs,
    "skewed_runs": gen_skewed_runs,
    "exponential_runs": gen_exponential_runs,
    "many_tiny_runs": gen_many_tiny_runs,
    "duplicate_heavy": gen_duplicate_heavy,
    "alternating_small_large_raw_runs": gen_alternating_small_large_raw_runs,
    "alternating_minrun_large_runs": gen_alternating_minrun_large_runs,
    "one_huge_tail_raw_runs": gen_one_huge_tail_raw_runs,
    "one_huge_tail_minrun_aware": gen_one_huge_tail_minrun_aware,
    "near_minrun_boundary": gen_near_minrun_boundary,
}


# =============================================================================
# 9. Measurement and experiment execution
# =============================================================================


def measure_algorithm(
    algorithm_name: str,
    algorithm: Algorithm,
    values: Sequence[int],
) -> dict[str, float | int | bool | str]:
    result, stats = algorithm(values)
    n = len(values)

    adjusted_features = summarize_run_lengths(
        stats.adjusted_runs, n, "adjusted"
    )

    return {
        "algorithm": algorithm_name,
        "correct": verify_sorted(values, result),
        "minrun": stats.minrun,
        "insertion_ratio": safe_divide(stats.insertion_elements, n),
        "extended_run_count": stats.extended_run_count,
        "weighted_merge_workload": stats.weighted_merge_workload,
        "merge_comparisons": stats.merge_comparisons,
        **adjusted_features,
    }


def run_experiment(
    *,
    sizes: Sequence[int],
    trials: int,
    random_seed: int,
    raw_results_path: Path,
) -> pd.DataFrame:
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not sizes or any(size <= 0 for size in sizes):
        raise ValueError("sizes must contain positive integers")

    rng = random.Random(random_seed)
    rows: list[dict[str, object]] = []

    for n in sizes:
        for data_type, generator in DATA_GENERATORS.items():
            for trial in range(trials):
                values = generator(n, rng)
                natural_features = analyze_natural_runs(values)

                for algorithm_name, algorithm in ALGORITHMS.items():
                    measurement = measure_algorithm(
                        algorithm_name, algorithm, values
                    )
                    measurement.update(
                        {
                            "n": n,
                            "data_type": data_type,
                            "trial": trial,
                            **natural_features,
                        }
                    )
                    rows.append(measurement)

                    print(
                        f"n={n}, data={data_type}, trial={trial}, "
                        f"algorithm={algorithm_name}, "
                        f"correct={measurement['correct']}, "
                        f"cost={measurement['weighted_merge_workload']}"
                    )

    results = pd.DataFrame(rows)

    if not results["correct"].all():
        failed = results.loc[~results["correct"]]
        raise AssertionError(
            "At least one sorting condition failed:\n"
            + failed[["n", "data_type", "trial", "algorithm"]].to_string(index=False)
        )

    raw_results_path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(raw_results_path, index=False, encoding="utf-8-sig")
    return results


# =============================================================================
# 10. Summary tables and derived measures
# =============================================================================


def summarize_results(results: pd.DataFrame) -> pd.DataFrame:
    summary = (
        results.groupby(["n", "data_type", "algorithm"], as_index=False)
        .agg(
            correctness_rate=("correct", "mean"),
            avg_natural_run_count=("natural_run_count", "mean"),
            avg_natural_normalized_run_count=(
                "natural_normalized_run_count", "mean"
            ),
            avg_natural_run_cv=("natural_run_cv", "mean"),
            avg_natural_max_run_ratio=("natural_max_run_ratio", "mean"),
            avg_natural_max_to_avg_ratio=(
                "natural_max_to_avg_ratio", "mean"
            ),
            avg_natural_run_entropy_bound_nH=(
                "natural_run_entropy_bound_nH", "mean"
            ),
            avg_adjusted_run_count=("adjusted_run_count", "mean"),
            avg_adjusted_normalized_run_count=(
                "adjusted_normalized_run_count", "mean"
            ),
            avg_adjusted_run_cv=("adjusted_run_cv", "mean"),
            avg_adjusted_max_run_ratio=("adjusted_max_run_ratio", "mean"),
            avg_adjusted_max_to_avg_ratio=(
                "adjusted_max_to_avg_ratio", "mean"
            ),
            avg_adjusted_run_entropy_bound_nH=(
                "adjusted_run_entropy_bound_nH", "mean"
            ),
            avg_minrun=("minrun", "mean"),
            avg_insertion_ratio=("insertion_ratio", "mean"),
            avg_extended_run_count=("extended_run_count", "mean"),
            avg_weighted_merge_workload=("weighted_merge_workload", "mean"),
            avg_merge_comparisons=("merge_comparisons", "mean"),
        )
    )

    summary["run_count_retention_ratio"] = summary.apply(
        lambda row: safe_divide(
            row["avg_adjusted_run_count"], row["avg_natural_run_count"]
        ),
        axis=1,
    )
    summary["entropy_retention_ratio"] = summary.apply(
        lambda row: safe_divide(
            row["avg_adjusted_run_entropy_bound_nH"],
            row["avg_natural_run_entropy_bound_nH"],
        ),
        axis=1,
    )
    summary["run_cv_change"] = (
        summary["avg_adjusted_run_cv"] - summary["avg_natural_run_cv"]
    )
    summary["max_run_ratio_change"] = (
        summary["avg_adjusted_max_run_ratio"]
        - summary["avg_natural_max_run_ratio"]
    )

    return summary


def feature_snapshot(
    summary: pd.DataFrame, algorithm_name: str, prefix: str
) -> pd.DataFrame:
    columns = [
        "avg_natural_run_count",
        "avg_natural_normalized_run_count",
        "avg_natural_run_cv",
        "avg_natural_max_run_ratio",
        "avg_natural_max_to_avg_ratio",
        "avg_natural_run_entropy_bound_nH",
        "avg_adjusted_run_count",
        "avg_adjusted_normalized_run_count",
        "avg_adjusted_run_cv",
        "avg_adjusted_max_run_ratio",
        "avg_adjusted_max_to_avg_ratio",
        "avg_adjusted_run_entropy_bound_nH",
        "avg_minrun",
        "avg_insertion_ratio",
        "avg_extended_run_count",
        "run_count_retention_ratio",
        "entropy_retention_ratio",
        "run_cv_change",
        "max_run_ratio_change",
    ]

    snapshot = summary.loc[
        summary["algorithm"] == algorithm_name,
        ["n", "data_type", *columns],
    ].copy()

    return snapshot.rename(
        columns={
            column: f"{prefix}_{column.removeprefix('avg_')}"
            for column in columns
        }
    )


def build_advantage_profile(
    summary: pd.DataFrame,
    *,
    metric: str = "avg_weighted_merge_workload",
) -> pd.DataFrame:
    pivot = (
        summary.pivot_table(
            index=["n", "data_type"],
            columns="algorithm",
            values=metric,
        )
        .reset_index()
        .rename_axis(columns=None)
        .rename(
            columns={
                "timsort_style_with_minrun": "timsort_with",
                "powersort_style_with_minrun": "powersort_with",
                "timsort_style_without_minrun": "timsort_without",
                "powersort_style_without_minrun": "powersort_without",
            }
        )
    )

    required = {
        "timsort_with",
        "powersort_with",
        "timsort_without",
        "powersort_without",
    }
    missing = required.difference(pivot.columns)
    if missing:
        raise ValueError(f"Missing experimental conditions: {sorted(missing)}")

    pivot["policy_gap_with_minrun"] = (
        pivot["timsort_with"] - pivot["powersort_with"]
    )
    pivot["policy_gap_without_minrun"] = (
        pivot["timsort_without"] - pivot["powersort_without"]
    )

    pivot["powersort_advantage_with_minrun"] = pivot.apply(
        lambda row: safe_divide(
            row["policy_gap_with_minrun"], row["timsort_with"]
        ),
        axis=1,
    )
    pivot["powersort_advantage_without_minrun"] = pivot.apply(
        lambda row: safe_divide(
            row["policy_gap_without_minrun"], row["timsort_without"]
        ),
        axis=1,
    )
    pivot["advantage_retention_ratio"] = pivot.apply(
        lambda row: safe_divide(
            row["policy_gap_with_minrun"], row["policy_gap_without_minrun"]
        ),
        axis=1,
    )

    with_features = feature_snapshot(
        summary, "timsort_style_with_minrun", "with_minrun"
    )
    without_features = feature_snapshot(
        summary, "timsort_style_without_minrun", "without_minrun"
    )

    profile = pivot.merge(with_features, on=["n", "data_type"], how="left")
    profile = profile.merge(
        without_features, on=["n", "data_type"], how="left"
    )
    profile["metric"] = metric
    return profile


def build_feature_correlation_summary(
    advantage_profile: pd.DataFrame,
) -> pd.DataFrame:
    targets = (
        "powersort_advantage_with_minrun",
        "powersort_advantage_without_minrun",
        "advantage_retention_ratio",
    )

    candidate_features = (
        "with_minrun_natural_normalized_run_count",
        "with_minrun_natural_run_cv",
        "with_minrun_natural_max_run_ratio",
        "with_minrun_natural_max_to_avg_ratio",
        "with_minrun_natural_run_entropy_bound_nH",
        "with_minrun_adjusted_normalized_run_count",
        "with_minrun_adjusted_run_cv",
        "with_minrun_adjusted_max_run_ratio",
        "with_minrun_adjusted_max_to_avg_ratio",
        "with_minrun_adjusted_run_entropy_bound_nH",
        "with_minrun_run_count_retention_ratio",
        "with_minrun_entropy_retention_ratio",
        "with_minrun_run_cv_change",
        "with_minrun_max_run_ratio_change",
        "with_minrun_insertion_ratio",
        "with_minrun_extended_run_count",
    )

    rows: list[dict[str, float | str]] = []

    for target in targets:
        for feature in candidate_features:
            data = (
                advantage_profile[[target, feature]]
                .replace([math.inf, -math.inf], math.nan)
                .dropna()
            )

            if (
                len(data) < 3
                or data[target].nunique() < 2
                or data[feature].nunique() < 2
            ):
                correlation = math.nan
            else:
                correlation = data[target].corr(data[feature])

            rows.append(
                {
                    "target": target,
                    "feature": feature,
                    "correlation": correlation,
                    "abs_correlation": (
                        abs(correlation) if not pd.isna(correlation) else math.nan
                    ),
                    "observations": len(data),
                }
            )

    return pd.DataFrame(rows).sort_values(
        ["target", "abs_correlation"],
        ascending=[True, False],
        na_position="last",
    )


# =============================================================================
# 11. Report figures
# =============================================================================


def save_plot(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"Saved figure: {path}")


def fixed_size_data(data: pd.DataFrame, fixed_n: int | None) -> tuple[pd.DataFrame, int]:
    selected_n = int(data["n"].max()) if fixed_n is None else fixed_n
    return data.loc[data["n"] == selected_n].copy(), selected_n


def plot_powersort_advantage(
    profile: pd.DataFrame, output_dir: Path, fixed_n: int | None = None
) -> None:
    data, selected_n = fixed_size_data(profile, fixed_n)

    plt.figure(figsize=(12, 6))
    plt.plot(
        data["data_type"],
        data["powersort_advantage_with_minrun"],
        marker="o",
        label="With minrun",
    )
    plt.plot(
        data["data_type"],
        data["powersort_advantage_without_minrun"],
        marker="o",
        label="Without minrun",
    )
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.title(f"Normalized Powersort-Style Merge-Cost Reduction (n={selected_n})")
    plt.xlabel("Data type")
    plt.ylabel("(Timsort-style cost − Powersort-style cost) / Timsort-style cost")
    plt.xticks(rotation=30, ha="right")
    plt.legend()
    save_plot(output_dir / "fig_powersort_advantage_with_vs_without_minrun.png")


def plot_advantage_retention(
    profile: pd.DataFrame, output_dir: Path, fixed_n: int | None = None
) -> None:
    data, selected_n = fixed_size_data(profile, fixed_n)
    finite = data.loc[data["advantage_retention_ratio"].notna()].copy()

    plt.figure(figsize=(12, 6))
    plt.bar(finite["data_type"], finite["advantage_retention_ratio"])
    plt.axhline(1, linestyle="--", linewidth=1)
    plt.axhline(0, linestyle=":", linewidth=1)
    plt.title(f"Retention of the Policy Gap After Minrun Extension (n={selected_n})")
    plt.xlabel("Data type")
    plt.ylabel("Policy gap with minrun / policy gap without minrun")
    plt.xticks(rotation=30, ha="right")
    save_plot(output_dir / "fig_advantage_retention_ratio.png")


def plot_feature_correlations(
    correlations: pd.DataFrame, output_dir: Path
) -> None:
    data = correlations.loc[
        correlations["target"] == "powersort_advantage_with_minrun"
    ].dropna(subset=["correlation"])

    data = data.nlargest(10, "abs_correlation").sort_values("correlation")
    if data.empty:
        return

    plt.figure(figsize=(12, 7))
    plt.barh(data["feature"], data["correlation"])
    plt.axvline(0, linestyle="--", linewidth=1)
    plt.title("Run Features Associated with Powersort-Style Cost Reduction")
    plt.xlabel("Pearson correlation")
    plt.ylabel("Run feature")
    save_plot(
        output_dir / "fig_feature_correlation_with_powersort_advantage.png"
    )


def plot_natural_vs_adjusted_run_count(
    summary: pd.DataFrame, output_dir: Path, fixed_n: int | None = None
) -> None:
    data = summary.loc[
        summary["algorithm"] == "timsort_style_with_minrun"
    ].copy()
    data, selected_n = fixed_size_data(data, fixed_n)

    positions = list(range(len(data)))
    width = 0.36

    plt.figure(figsize=(12, 6))
    plt.bar(
        [position - width / 2 for position in positions],
        data["avg_natural_run_count"],
        width=width,
        label="Natural runs",
    )
    plt.bar(
        [position + width / 2 for position in positions],
        data["avg_adjusted_run_count"],
        width=width,
        label="Adjusted runs",
    )
    plt.title(f"Natural and Adjusted Run Counts (n={selected_n})")
    plt.xlabel("Data type")
    plt.ylabel("Run count")
    plt.xticks(positions, data["data_type"], rotation=30, ha="right")
    plt.legend()
    save_plot(output_dir / "fig_natural_vs_adjusted_run_count.png")


def plot_entropy_retention(
    summary: pd.DataFrame, output_dir: Path, fixed_n: int | None = None
) -> None:
    data = summary.loc[
        summary["algorithm"] == "timsort_style_with_minrun"
    ].copy()
    data, selected_n = fixed_size_data(data, fixed_n)

    plt.figure(figsize=(12, 6))
    plt.plot(data["data_type"], data["entropy_retention_ratio"], marker="o")
    plt.axhline(1, linestyle="--", linewidth=1)
    plt.title(f"Run-Entropy Retention After Minrun Extension (n={selected_n})")
    plt.xlabel("Data type")
    plt.ylabel("Adjusted nH / natural nH")
    plt.xticks(rotation=30, ha="right")

    # Preserve the filename already referenced by the report.
    save_plot(output_dir / "fig_entropy_distortion_ratio.png")


def plot_feature_vs_advantage(
    profile: pd.DataFrame,
    *,
    feature: str,
    output_path: Path,
) -> None:
    target = "powersort_advantage_with_minrun"
    data = (
        profile[["data_type", feature, target]]
        .replace([math.inf, -math.inf], math.nan)
        .dropna()
    )
    if data.empty:
        return

    plt.figure(figsize=(9, 6))
    plt.scatter(data[feature], data[target])
    plt.axhline(0, linestyle="--", linewidth=1)
    plt.title(f"{feature} vs Powersort-Style Cost Reduction")
    plt.xlabel(feature)
    plt.ylabel(target)
    save_plot(output_path)


def generate_report_figures(
    summary: pd.DataFrame,
    profile: pd.DataFrame,
    correlations: pd.DataFrame,
    output_dir: Path,
) -> None:
    plot_powersort_advantage(profile, output_dir)
    plot_advantage_retention(profile, output_dir)
    plot_feature_correlations(correlations, output_dir)
    plot_natural_vs_adjusted_run_count(summary, output_dir)
    plot_entropy_retention(summary, output_dir)
    plot_feature_vs_advantage(
        profile,
        feature="with_minrun_adjusted_run_cv",
        output_path=(
            output_dir
            / "fig_with_minrun_adjusted_run_cv_vs_powersort_advantage.png"
        ),
    )
    plot_feature_vs_advantage(
        profile,
        feature="with_minrun_adjusted_max_run_ratio",
        output_path=(
            output_dir
            / "fig_with_minrun_adjusted_max_run_ratio_vs_powersort_advantage.png"
        ),
    )



# =============================================================================
# 12. Validation
# =============================================================================


def validate_run_partition(runs: Sequence[tuple[int, int]], n: int) -> None:
    if n == 0:
        if runs:
            raise AssertionError("An empty input must not contain runs")
        return

    if not runs or runs[0][0] != 0 or runs[-1][1] != n:
        raise AssertionError("Runs must cover the complete input")

    for (left, right), (next_left, next_right) in zip(runs, runs[1:]):
        if not (left < right and right == next_left and next_left < next_right):
            raise AssertionError("Runs must be non-empty, adjacent, and ordered")



# =============================================================================
# 13. Main workflow
# =============================================================================


def run_analysis(
    *,
    output_root: Path = Path("outputs"),
    sizes: Sequence[int] = DEFAULT_SIZES,
    trials: int = DEFAULT_TRIALS,
    random_seed: int = RANDOM_SEED,
) -> None:
    main_dir = output_root / "main_results"
    appendix_dir = output_root / "appendix"

    main_dir.mkdir(parents=True, exist_ok=True)
    appendix_dir.mkdir(parents=True, exist_ok=True)


    raw_results = run_experiment(
        sizes=sizes,
        trials=trials,
        random_seed=random_seed,
        raw_results_path=appendix_dir / "raw_experiment_results.csv",
    )
    summary = summarize_results(raw_results)
    profile = build_advantage_profile(summary)
    correlations = build_feature_correlation_summary(profile)

    summary.to_csv(
        main_dir / "run_distribution_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )
    profile.to_csv(
        main_dir / "powersort_advantage_profile.csv",
        index=False,
        encoding="utf-8-sig",
    )
    correlations.to_csv(
        main_dir / "run_feature_correlation_with_advantage.csv",
        index=False,
        encoding="utf-8-sig",
    )

    generate_report_figures(summary, profile, correlations, main_dir)

    print("\nAnalysis finished successfully.")
    print(f"Main report outputs: {main_dir}")
    print(f"Raw experiment data: {appendix_dir}")


if __name__ == "__main__":
    run_analysis()