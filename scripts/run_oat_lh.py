#!/usr/bin/env python3
"""
run_oat_lh.py

Automates creating and submitting the OAT low/high 5-day bound runs
(2025-08-01 through 2025-08-05), each branching as a CIME hybrid run from
the 3-month CTL spin-up's restart (see scripts/OAT.sh and MMPPE-info/
MMPPE.md's "One-At-a-Time Test": "In each OAT simulation, one parameter is
set to its lower or upper bound while all others remain at their default
values").

Design (see conversation this came out of for the full reasoning):
  - Uses `create_clone --keepexe` off the already-built CTL case rather
    than a fresh create_newcase+case.build per run -- every L/H run is
    identical to CTL except for a hybrid-restart env_run.xml block and one
    parameter's namelist override, so there's nothing to recompile.
  - Parameter table (oat_parameters.csv, same directory as this script):
    protocol name -> actual CAM6 namelist variable(s), cross-referenced
    from ppe_changes_incorporated.txt section 6 (the authoritative record
    of what this branch actually wired up) -- NOT from
    ~/LHS_example/CAM6_param_range_list.txt directly, which uses the same
    protocol names but doesn't know this branch's namelist variable names,
    and includes 2 parameters (rad_bc_ni, rad_oc_ni) that section 6c
    documents as deliberately un-implemented (no knob exists in CAM6 or
    CAM7 at all -- refractive index is baked into a physprop lookup
    table). Those, plus emi_cmr_ff/emi_cmr_bb (also 6c), are excluded from
    oat_parameters.csv entirely since there is nothing to set.
  - low_value/high_value in oat_parameters.csv are literally the string
    PLACEHOLDER -- per-parameter real values will eventually come from a
    file in ~/LHS_example/ (CAM6_param_range_list.txt exists there already
    but is a protocol-name/value reference, not this namelist-ready
    table -- see oat_parameters.csv's own notes column for where each
    parameter's real range should come from). This script REFUSES to
    create/submit a case whose value is still PLACEHOLDER, rather than
    silently launching a run with a made-up number.
  - Idempotent: if a requested case's directory already exists, it's
    skipped (not re-cloned, not re-submitted).

TODO (blocking, same as scripts/OAT.sh -- fill in once decided there):
  - SCRIPTDIR: which CIME checkout's cime/scripts has clean-CAM wired in
    as its cam external.
  - CTL_EXP / CTL_CASEROOT: must match whatever EXP scripts/OAT.sh
    actually used, and that CTL case must have been run to completion
    (through 2025-07-31/2025-08-01) so its restart files exist for
    GET_REFCASE to find -- this script doesn't check that they exist, only
    that the CTL case *directory* does. It also doesn't check that CTL is
    finished running, only that it exists -- if it's still queued/running
    when a clone is submitted, the clone's hybrid restart will fail; check
    yourself before running this on many parameters at once.
  - RUN_REFDIR is not set explicitly below -- CIME's hybrid-restart lookup
    convention on derecho typically finds it automatically from
    RUN_REFCASE's own rundir once that case has run, but if GET_REFCASE
    fails to locate restarts, set RUN_REFDIR explicitly to the CTL case's
    run (or short-term-archive) directory.

Usage:
    python run_oat_lh.py micro_ccraut zmconv_dmpdz         # both bounds
    python run_oat_lh.py micro_ccraut --bound low          # low only
    python run_oat_lh.py --all                             # every row in
                                                            # oat_parameters.csv
    python run_oat_lh.py --list                            # show available
                                                            # parameter names
    python run_oat_lh.py micro_ccraut --dry-run            # print the
                                                            # commands without
                                                            # running them
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARAM_TABLE = os.path.join(SCRIPT_DIR, "oat_parameters.csv")

# TODO -- see module docstring; must match scripts/OAT.sh once that's filled in.
SCRIPTDIR = ""
CTL_EXP = "MMPPE_OAT_CTL"
EXPERIMENTS_DIR = "/glade/work/bduran/MMPPE-ACI"
CTL_CASEROOT = os.path.join(EXPERIMENTS_DIR, CTL_EXP)
PROJECTCODE = "UCSD0085"

# Hybrid restart: branch from the CTL spin-up's final restart. 2025-08-01 is
# not a guess -- RUN_STARTDATE=2025-05-01 + STOP_N=3/STOP_OPTION=nmonths in
# OAT.sh lands exactly there (May+June+July = 3 full months from May 1).
REF_DATE = "2025-08-01"
RUN_STARTDATE = "2025-08-01"
STOP_N = "5"
STOP_OPTION = "ndays"

BOUND_SUFFIX = {"low": "L", "high": "H"}


def load_param_table(path: str) -> dict[str, dict]:
    table = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            table[row["protocol_name"]] = row
    return table


def run(cmd: list[str], cwd: str | None, dry_run: bool) -> None:
    printable = " ".join(cmd)
    print(f"    $ {printable}" + (f"   (cwd={cwd})" if cwd else ""))
    if dry_run:
        return
    subprocess.run(cmd, cwd=cwd, check=True)


def append_user_nl_cam(caseroot: str, namelist_vars: list[str], value: str, dry_run: bool) -> None:
    lines = [f"{var} = {value}\n" for var in namelist_vars]
    print(f"    >> user_nl_cam += {[l.strip() for l in lines]}")
    if dry_run:
        return
    with open(os.path.join(caseroot, "user_nl_cam"), "a") as f:
        f.writelines(lines)


def create_one(protocol_name: str, row: dict, bound: str, dry_run: bool) -> None:
    value = row["low_value"] if bound == "low" else row["high_value"]
    suffix = BOUND_SUFFIX[bound]
    exp = f"MMPPE_OAT_{protocol_name}_{suffix}"
    caseroot = os.path.join(EXPERIMENTS_DIR, exp)

    print(f"\n[{protocol_name} / {bound}] -> {exp}")

    if os.path.isdir(caseroot):
        print(f"    [skip] case directory already exists: {caseroot}")
        return

    if value.strip().upper() == "PLACEHOLDER":
        print(
            f"    [skip] {protocol_name}'s {bound} value is still PLACEHOLDER in "
            f"{PARAM_TABLE} -- fill in the real value (see ~/LHS_example/ and the "
            "notes column) before this case can be created."
        )
        return

    namelist_vars = [v.strip() for v in row["namelist_vars"].split(";")]

    run(
        ["./create_clone", "--case", caseroot, "--clone", CTL_CASEROOT, "--keepexe"],
        cwd=SCRIPTDIR,
        dry_run=dry_run,
    )

    xmlchanges = {
        "CONTINUE_RUN": "FALSE",
        "RUN_TYPE": "hybrid",
        "RUN_REFCASE": CTL_EXP,
        "RUN_REFDATE": REF_DATE,
        "GET_REFCASE": "TRUE",
        "RUN_STARTDATE": RUN_STARTDATE,
        "STOP_N": STOP_N,
        "STOP_OPTION": STOP_OPTION,
        "REST_N": STOP_N,
        "REST_OPTION": STOP_OPTION,
        "RESUBMIT": "0",
    }
    for key, val in xmlchanges.items():
        run(["./xmlchange", f"{key}={val}"], cwd=caseroot, dry_run=dry_run)

    append_user_nl_cam(caseroot, namelist_vars, value, dry_run)

    run(["qcmd", "-A", PROJECTCODE, "--", "./case.build", "--skip-provenance-check"],
        cwd=caseroot, dry_run=dry_run)
    run(["./case.submit"], cwd=caseroot, dry_run=dry_run)

    print(f"    -> submitted {exp}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("parameters", nargs="*", help="protocol parameter name(s) from oat_parameters.csv")
    parser.add_argument("--all", action="store_true", help="process every parameter in the table")
    parser.add_argument("--list", action="store_true", help="list available parameter names and exit")
    parser.add_argument("--bound", choices=["low", "high", "both"], default="both")
    parser.add_argument("--params-file", default=PARAM_TABLE, help="override path to the parameter table CSV")
    parser.add_argument("--dry-run", action="store_true", help="print commands without running them")
    args = parser.parse_args()

    table = load_param_table(args.params_file)

    if args.list:
        for name, row in table.items():
            print(f"  {name:28s} ({row['category']:11s}) -> {row['namelist_vars']}")
        return 0

    if not SCRIPTDIR:
        print("ERROR: SCRIPTDIR/CTL_EXP must be set at the top of this script "
              "(same TODOs as scripts/OAT.sh) before it can run for real.")
        if not args.dry_run:
            return 1
        print("(continuing anyway since --dry-run was given)")

    if args.all:
        requested = list(table.keys())
    else:
        requested = args.parameters
    if not requested:
        parser.error("give one or more parameter names, or --all / --list")

    unknown = [p for p in requested if p not in table]
    if unknown:
        print(f"ERROR: unknown parameter name(s): {unknown}")
        print(f"Run with --list to see available names from {args.params_file}")
        return 1

    bounds = ["low", "high"] if args.bound == "both" else [args.bound]

    for name in requested:
        row = table[name]
        for bound in bounds:
            create_one(name, row, bound, args.dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
