# Run Distribution and Minrun Preprocessing in Adaptive Merge Sorting

An empirical study of how run-distribution features and `minrun` preprocessing affect the observable merge-cost difference between Timsort-style and Powersort-style merge policies.

## Research question

Which run-distribution features amplify or weaken the visible advantage of a Powersort-style merge policy over a Timsort-style merge policy, and how does `minrun` preprocessing change this relationship?

The project separates two effects that are often discussed together:

1. **Preprocessing effect:** natural runs are transformed into adjusted runs through optional `minrun` extension.
2. **Merge-policy effect:** Timsort-style and Powersort-style policies construct different merge trees from the adjusted runs.

## Experimental design

The experiments use a 2×2 design:

| Preprocessing | Timsort-style | Powersort-style |
|---|---:|---:|
| With `minrun` | ✓ | ✓ |
| Without `minrun` | ✓ | ✓ |

Synthetic inputs include balanced runs, skewed runs, exponential runs, many tiny runs, duplicate-heavy data, alternating run sizes, dominant tails, and cases near the `minrun` boundary.

The primary response variable is the normalized merge-cost difference:

```text
(Timsort-style cost - Powersort-style cost) / Timsort-style cost
```

A positive value means the Powersort-style policy produced a lower merge tree cost for that condition.

## Repository structure

```text
.
├── src/
│   └── run_distribution_analysis.py
├── report/
│   ├── report.md
│   └── report.docx
├── figures/
│   └── generated report figures
├── results/
│   ├── main/
│   │   └── summary and analysis CSV files
│   └── raw/
│       └── raw_experiment_results.csv
├── requirements.txt
├── .gitignore
└── LICENSE
```

## Setup

Python 3.10 or later is recommended.

```bash
python -m venv .venv
```

Activate the environment:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the experiment

Run from the repository root:

```bash
python src/run_distribution_analysis.py
```

The script generates a new `outputs/` directory containing raw experiment data, summary tables, figures, and case-study merge trees. The committed files under `results/` and `figures/` are the validated outputs used in the report.

The default full experiment contains:

- input sizes: `1000`, `5000`, and `10000`;
- 12 data distributions;
- 5 trials per condition;
- 4 algorithm conditions;
- 720 sorting runs in total.

Each run is checked against Python's `sorted()` result. The script also validates run partitions, merge counts, and merge-cost accounting.

## Main outputs

- `powersort_advantage_profile.csv`: with/without-`minrun` policy gaps and normalized cost differences.
- `run_distribution_summary.csv`: natural-run and adjusted-run feature summaries.
- `run_feature_correlation_with_advantage.csv`: exploratory Pearson correlations between structural features and policy-cost differences.
- `fig_powersort_advantage_with_vs_without_minrun.png`: central comparison figure.
- `fig_advantage_retention_ratio.png`: change in the policy gap after `minrun` preprocessing.

## Scope and limitations

This repository studies simplified **Timsort-style** and **Powersort-style** merge policies. It is not a complete reimplementation or runtime benchmark of CPython Timsort/Powersort. Galloping mode, cache behavior, low-level memory optimizations, and production implementation details are outside the main scope.

The correlation analysis is exploratory and should not be interpreted as causal inference.

## Report references

The report cites only the following three papers:

1. J. I. Munro and S. Wild, “Nearly-Optimal Mergesorts: Fast, Practical Sorting Methods That Optimally Adapt to Existing Runs,” ESA 2018.
2. N. Auger, V. Jugé, C. Nicaud, and C. Pivoteau, “On the Worst-Case Complexity of TimSort,” ESA 2018.
3. S. Buss and A. Knop, “Strategies for Stable Merge Sorting,” SODA 2019.

Full bibliographic information appears in `report/report.md` and `report/report.docx`.

## Author

Wen-Yu Liao — academic course project, 2026.
