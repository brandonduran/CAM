#!/usr/bin/env python3
"""
generate_oat_summary.py

Builds a global/time-mean summary CSV of the 14 MMPPE "OAT variables to
test" (MMPPE-info/OAT_variable_mapping.txt) for every completed OAT L/H
5-day run, in the same row/column form as the ICON-HAM reference at
~/mmppe-repo/phase-4/MMPPE/ICON-HAM_5d_OAT.csv:

    experiment,od550aer,abs550aer,angstrm550_865,ssa550,ccns.3,ccncol.3,
    cdnc_incl_ct,clt,cllvi,clivi,pr,scre,lcre,fnet

One row per parameter/bound (e.g. "conv_entrpen_H"), using the CAM6 field
mapped in OAT_variable_mapping.txt for each column. Completion is checked
the same way run_oat_lh.py checks it (via that module's is_completed()) --
parameters whose L or H run hasn't finished are simply left out, not
written with blanks/NaNs.

"base" row: prefers MMPPE_OAT_base -- a dedicated unperturbed 5-day branch
off the same CTL restart the L/H runs use (run_oat_lh.py --base), added
2026-08-10 specifically because CTL's 3-month spin-up mean was a mismatched
baseline (comparing a 5-day-window run against a seasonal mean made nearly
every parameter's Low/High land on the same side of "base" -- confirmed
against the ICON-HAM reference, which doesn't show that pattern). Falls
back to CTL's 3-month spin-up mean (MMPPE_OAT_CTL's single h0 file, one
record/day for the full May-Aug spin-up) if MMPPE_OAT_base hasn't finished
yet. If neither is available, "base" is left out entirely.

Requires numpy + xarray + netCDF4 (not in the default `python3` on this
system) -- use e.g.:
    /glade/work/bduran/conda-envs/ppe-test/bin/python generate_oat_summary.py

Usage:
    python generate_oat_summary.py                  # write scripts/oat_5d_summary.csv
    python generate_oat_summary.py --output foo.csv  # override output path
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import run_oat_lh  # noqa: E402  (needs sys.path set up first)

try:
    import xarray as xr
except ImportError:
    sys.exit(
        "ERROR: this script needs numpy/xarray/netCDF4, which aren't in the "
        "default python3. Try:\n"
        "  /glade/work/bduran/conda-envs/ppe-test/bin/python "
        + os.path.abspath(__file__)
    )

DEFAULT_OUTPUT = os.path.join(SCRIPT_DIR, "oat_5d_summary.csv")

# Column order matches the ICON-HAM reference CSV exactly, for
# side-by-side comparability. Each entry is (csv_column_name, compute_fn),
# where compute_fn(ds) -> float, given an opened xarray.Dataset for one
# case's h0 history file. See MMPPE-info/OAT_variable_mapping.txt for the
# derivation/justification of every mapping below.


def _gw_weighted_mean(ds: "xr.Dataset", da: "xr.DataArray") -> float:
    """Area-weighted (via the file's own Gaussian latitude weights, `gw`)
    then time-mean of `da`, skipping NaNs (day-only fields are NaN at
    night/polar-night grid points via their _FillValue/missing_value,
    which xarray's default decode_cf already converts to NaN on open)."""
    reduce_dims = [d for d in ("lat", "lon") if d in da.dims]
    result = da.weighted(ds["gw"]).mean(dim=reduce_dims, skipna=True)
    if "time" in result.dims:
        result = result.mean(dim="time", skipna=True)
    return float(result.values)


def _bottom_level(ds: "xr.Dataset", da: "xr.DataArray") -> "xr.DataArray":
    """Select the model level closest to the surface -- the level with the
    largest hybm (hybrid-B) coefficient, i.e. the last index in this
    branch's top-to-bottom level ordering (hybm runs 0 at the model top to
    ~0.99 at the surface -- verified 2026-08-10 against an actual OAT
    history file, not assumed)."""
    bottom_idx = int(ds["hybm"].argmax())
    return da.isel(lev=bottom_idx)


VARIABLES: list[tuple[str, "callable"]] = [
    ("od550aer", lambda ds: _gw_weighted_mean(ds, ds["AODVIS"])),
    ("abs550aer", lambda ds: _gw_weighted_mean(ds, ds["AODABS"])),
    ("angstrm550_865", lambda ds: _gw_weighted_mean(ds, ds["ANGSTRM_550_865"])),
    ("ssa550", lambda ds: _gw_weighted_mean(ds, ds["SSAVIS"])),
    ("ccns.3", lambda ds: _gw_weighted_mean(ds, _bottom_level(ds, ds["CCN7"]))),
    ("ccncol.3", lambda ds: _gw_weighted_mean(ds, ds["CCN7COL"])),
    # Ratio of global means (2026-08-10 user decision), not a pointwise
    # ratio -- recovers the in-cloud mean from two grid-mean fields.
    ("cdnc_incl_ct", lambda ds: _gw_weighted_mean(ds, ds["ACTNL"]) / _gw_weighted_mean(ds, ds["FCTL"])),
    ("clt", lambda ds: _gw_weighted_mean(ds, ds["CLDTOT"])),
    ("cllvi", lambda ds: _gw_weighted_mean(ds, ds["TGCLDLWP"])),
    ("clivi", lambda ds: _gw_weighted_mean(ds, ds["TGCLDIWP"])),
    # PRECT is m/s liquid-water-equivalent; x1000 (density of water) -> kg/m2/s.
    ("pr", lambda ds: _gw_weighted_mean(ds, ds["PRECT"]) * 1000.0),
    ("scre", lambda ds: _gw_weighted_mean(ds, ds["SWCF"])),
    ("lcre", lambda ds: _gw_weighted_mean(ds, ds["LWCF"])),
    ("fnet", lambda ds: _gw_weighted_mean(ds, ds["FSNTOA"]) - _gw_weighted_mean(ds, ds["FLUT"])),
]


def find_history_file(exp: str) -> str | None:
    matches = sorted(glob.glob(os.path.join(run_oat_lh.ARCHIVE_ROOT, exp, "atm", "hist", f"{exp}.cam.h0.*.nc")))
    if not matches:
        return None
    if len(matches) > 1:
        print(f"    [warn] {exp}: {len(matches)} h0 files found, using all of them together")
        return matches  # let xr.open_mfdataset handle concatenation
    return matches[0]


def compute_row(label: str, exp: str) -> dict | None:
    path = find_history_file(exp)
    if path is None:
        print(f"    [skip] {label}: no archived h0 history file found for {exp}")
        return None

    try:
        ds = xr.open_mfdataset(path, decode_cf=True, combine="by_coords") if isinstance(path, list) \
            else xr.open_dataset(path, decode_cf=True)
    except Exception as e:
        print(f"    [skip] {label}: failed to open {path}: {e}")
        return None

    row = {"experiment": label}
    try:
        with ds:
            for col_name, compute_fn in VARIABLES:
                row[col_name] = compute_fn(ds)
    except KeyError as e:
        print(f"    [skip] {label}: missing expected history field {e} in {path}")
        return None
    except Exception as e:
        print(f"    [skip] {label}: error computing summary from {path}: {e}")
        return None

    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--params-file", default=run_oat_lh.PARAM_TABLE, help="override path to the parameter table CSV")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="output CSV path")
    args = parser.parse_args()

    table = run_oat_lh.load_param_table(args.params_file)

    rows = []

    if run_oat_lh.is_completed(run_oat_lh.BASE_EXP):
        print(f"[base] -> {run_oat_lh.BASE_EXP} (unperturbed 5-day control)")
        base_row = compute_row("base", run_oat_lh.BASE_EXP)
    else:
        print(
            f"[base] -> {run_oat_lh.CTL_EXP} (3-month spin-up mean fallback -- "
            f"{run_oat_lh.BASE_EXP} not yet completed; run `run_oat_lh.py --base` "
            "then build/submit it for a proper matched-window baseline)"
        )
        base_row = compute_row("base", run_oat_lh.CTL_EXP)
    if base_row is not None:
        rows.append(base_row)

    for name in table:
        for bound in ("low", "high"):
            suffix = run_oat_lh.BOUND_SUFFIX[bound]
            exp = f"MMPPE_OAT_{name}_{suffix}"
            label = f"{name}_{suffix}"

            if not run_oat_lh.is_completed(exp):
                print(f"[{label}] -> {exp}\n    [skip] not yet completed")
                continue

            print(f"[{label}] -> {exp}")
            row = compute_row(label, exp)
            if row is not None:
                rows.append(row)

    if not rows:
        print("\nNo rows to write (nothing completed yet) -- not writing an output file.")
        return 0

    header = ["experiment"] + [col for col, _ in VARIABLES]
    with open(args.output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row["experiment"]] + [f"{row[col]:.4e}" for col, _ in VARIABLES])

    print(f"\nWrote {len(rows)} row(s) -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
