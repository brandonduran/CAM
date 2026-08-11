#!/usr/bin/env python3
"""
plot_OAT.py

Adapted from ~/mmppe-repo/phase-4/MMPPE/plot_OAT.py (the ICON-HAM 5-day OAT
plotting script) for this branch's CAM6 MMPPE PPE. Same scatter-plot logic
(one plot per output variable, Low/High points relative to a "base" run,
grouped by parameter) -- only the environment-specific bits changed:

  - Reads scripts/oat_5d_summary.csv by default (see generate_oat_summary.py,
    which builds it from completed OAT L/H archive output) instead of
    ICON-HAM_5d_OAT.csv.
  - Uses the Agg backend and never calls plt.show() -- this runs on HPC
    login nodes without a display; the original's plt.show() was a no-op
    there anyway once run non-interactively, but calling it is misleading.
  - Writes PNGs to scripts/oat_plots/ by default instead of the cwd.
  - Dropped the original's stray, unused `from pyexpat import model` import
    (an apparent copy-paste artifact -- shadowed by the local `model`
    parameter and never called).
  - model/ppename/csv/outdir are now CLI-overridable instead of hardcoded.

Usage:
    python plot_OAT.py                       # scripts/oat_5d_summary.csv -> scripts/oat_plots/
    python plot_OAT.py --csv foo.csv --outdir bar/
"""

from __future__ import annotations

import argparse
import os

import matplotlib
matplotlib.use("Agg")  # no display on HPC login/batch nodes
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CSV = os.path.join(SCRIPT_DIR, "oat_5d_summary.csv")
DEFAULT_OUTDIR = os.path.join(SCRIPT_DIR, "oat_plots")


def plot_OAT_scatter(data, var, model, ppename, outdir, ref_diff=False, width=9, height=3):
    '''
    ref_diff: True for for relative diff (in %) of global mean;  False for just global mean
    '''
    plt.figure(figsize=(width, height))

    base_val = data.get(f'base', np.nan)

    # Collect values by grouping L and H under the same base label
    grouped_data = {}
    for key, val in data.items():
        label = key
        if label == 'base':
            continue
        if label.endswith(('L', 'H')):
            base_label = label[:-2]  # Remove '_L' or '_H'
            suffix = label[-1]
            if base_label not in grouped_data:
                grouped_data[base_label] = {}
            grouped_data[base_label][suffix] = ((float(val) - base_val) / base_val * 100) if ref_diff else float(val)


    x_labels = list(grouped_data.keys())
    x_pos = range(len(x_labels))

    # Scatter plot values
    for i, label in enumerate(x_labels):
        values = grouped_data[label]
        if 'L' in values:
            plt.scatter(i, values['L'], color='blue', label='Low' if i == 0 else "", zorder=3, alpha=0.7, marker='s')
        if 'H' in values:
            plt.scatter(i, values['H'], color='orange', label='High' if i == 0 else "", zorder=3, alpha=0.7)


    plt.axhline(0 if ref_diff else base_val, color='red', linestyle='--', linewidth=1, label='Base')

    plt.xticks(ticks=x_pos, labels=x_labels, rotation=90)
    plt.ylabel(f'{var} [%]' if ref_diff else var)
    plt.title(f'Relative difference to base run [{ppename}]' if ref_diff else 'Global Mean')
    plt.grid(axis='y', linestyle='--', alpha=0.7)
     # Legend outside
    plt.legend(loc='center left', bbox_to_anchor=(1.0, 0.5))
    plt.tight_layout(rect=[0, 0, 0.85, 1])  # Make space for the legend

    plt.savefig(os.path.join(outdir, f'{model}_{ppename}_{var}.png'), bbox_inches='tight')
    plt.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", default=DEFAULT_CSV, help="input summary CSV (default: scripts/oat_5d_summary.csv)")
    parser.add_argument("--outdir", default=DEFAULT_OUTDIR, help="directory to write PNGs to (default: scripts/oat_plots/)")
    parser.add_argument("--model", default="CAM6", help="model label used in plot titles/filenames (default: CAM6)")
    parser.add_argument("--ppename", default="5d_OAT", help="PPE test label used in plot titles/filenames (default: 5d_OAT)")
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        parser.error(
            f"{args.csv} not found -- run generate_oat_summary.py first to build it "
            "from completed OAT L/H archive output."
        )

    os.makedirs(args.outdir, exist_ok=True)

    df = pd.read_csv(args.csv, index_col="experiment")

    for var in df.columns:
        plot_OAT_scatter(
            data=df[var],
            var=var,
            model=args.model,
            ppename=args.ppename,
            outdir=args.outdir,
            ref_diff=True,
            width=14,
            height=4,
        )

    print(f"Wrote {len(df.columns)} plot(s) -> {args.outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
