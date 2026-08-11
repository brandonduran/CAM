#!/usr/bin/env python3
"""
run_oat_lh.py

Automates creating and submitting the OAT low/high 5-day bound runs
(2025-08-01 through 2025-08-05), each branching as a CIME branch run from
the 3-month CTL spin-up's restart (see scripts/OAT.sh and MMPPE-info/
MMPPE.md's "One-At-a-Time Test": "In each OAT simulation, one parameter is
set to its lower or upper bound while all others remain at their default
values").

Design (see conversation this came out of for the full reasoning):
  - Uses `create_clone --keepexe` off the already-built CTL case rather
    than a fresh create_newcase+case.build per run -- every L/H run is
    identical to CTL except for a branch-restart env_run.xml block and one
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

TODO:
  - SCRIPTDIR / CTL_EXP are now filled in to match scripts/OAT.sh's
    resolved checkout and EXP. That CTL case (MMPPE_OAT_CTL) must still
    run to completion (through 2025-07-31/2025-08-01, currently
    queued as of 2026-08-07) so its restart files exist for GET_REFCASE
    to find -- this script doesn't check that they exist, only that the
    CTL case *directory* does. It also doesn't check that CTL is finished
    running, only that it exists -- if it's still queued/running when a
    clone is submitted, the clone's branch restart will fail; check
    yourself (`qstat -u $USER`) before running this for real.
  - RUN_REFDIR is set explicitly below to CTL's short-term-archive rest/
    directory (2026-08-08 fix): CIME's stage_refcase() (cime/scripts/lib/
    CIME/case/check_input_data.py) only auto-locates the refcase if
    RUN_REFDIR is a *relative* path, in which case it looks under
    DIN_LOC_ROOT/RUN_REFDIR/RUN_REFCASE/RUN_REFDATE -- i.e. inputdata, not
    the CTL case's own run directory. That's what produced the
    "Refcase not found in /glade/campaign/.../cesm2_init/MMPPE_OAT_CTL/
    2025-08-01" error on the first parameter submitted: RUN_REFDIR
    defaulted to the relative "cesm2_init". Passing an *absolute* path
    makes CIME use it as-is (with an existence check, no download
    attempt) -- see REF_DIR below, confirmed to exist and contain
    rpointer.* files for MMPPE_OAT_CTL's 2025-08-01 restart.
  - RUN_TYPE switched from hybrid to branch (2026-08-09 fix): CAM's
    hybrid mode (cime_config/buildnml) requires an ncdata IC file named
    <RUN_REFCASE>.cam.i.<RUN_REFDATE>-<RUN_REFTOD>.nc, which CAM only
    writes when inithist crosses its trigger condition (default
    inithist='YEARLY', which never fired for CTL's May-Aug spin-up since
    it doesn't cross a Jan 1 boundary) -- that missing file was the
    "(GETFIL): attempting to find local file
    MMPPE_OAT_CTL.cam.i.2025-08-01-00000.nc" failure on all 12 previously
    submitted L/H runs. Branch mode uses cam_branch_file, pointed at the
    .r. restart file, which CTL already has for every component. Per
    CIME's own config_component.xml RUN_TYPE docs, branch is also the
    run type explicitly recommended "when sensitivity or parameter
    studies are required" -- a better methodological fit for OAT than
    hybrid's relaxed/non-bit-for-bit restart anyway. One behavior change:
    branch mode ignores RUN_STARTDATE (start date comes from the
    refcase's restart) -- harmless here since RUN_STARTDATE is already
    set to REF_DATE below.

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
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARAM_TABLE = os.path.join(SCRIPT_DIR, "oat_parameters.csv")
STATUS_FILE = os.path.join(SCRIPT_DIR, "oat_status.csv")

# Matches scripts/OAT.sh's SCRIPTDIR (verified clean checkout_externals -S, 2026-08-07).
SCRIPTDIR = "/glade/work/bduran/clean-CAM/cime/scripts"
CTL_EXP = "MMPPE_OAT_CTL"
EXPERIMENTS_DIR = "/glade/work/bduran/MMPPE-ACI"
CTL_CASEROOT = os.path.join(EXPERIMENTS_DIR, CTL_EXP)
PROJECTCODE = "UCSD0085"

# Hybrid restart: branch from the CTL spin-up's final restart. 2025-08-01 is
# not a guess -- RUN_STARTDATE=2025-05-01 + STOP_N=3/STOP_OPTION=nmonths in
# OAT.sh lands exactly there (May+June+July = 3 full months from May 1).
REF_DATE = "2025-08-01"

# Absolute path required (see TODO note above) so CIME's stage_refcase()
# uses it directly instead of searching under DIN_LOC_ROOT. CTL has
# DOUT_S=TRUE, so this is its short-term-archive rest/ directory rather
# than its live RUNDIR -- confirmed 2026-08-08 to contain both the
# 2025-08-01 restart files and all rpointer.* files.
REF_DIR = f"/glade/derecho/scratch/{os.environ.get('USER', 'bduran')}/archive/{CTL_EXP}/rest/{REF_DATE}-00000"

# Short-term-archive root: used to detect parameters that have already been
# run to completion (case.st_archive'd), even if their caseroot under
# EXPERIMENTS_DIR was since cleaned up.
ARCHIVE_ROOT = f"/glade/derecho/scratch/{os.environ.get('USER', 'bduran')}/archive"

RUN_STARTDATE = "2025-08-01"
STOP_N = "5"
STOP_OPTION = "ndays"

# The date each L/H run's restart should land on if it finishes all 5 days
# (REF_DATE + STOP_N days). A case is "complete" iff
# ARCHIVE_ROOT/<exp>/rest/<EXPECTED_COMPLETION_DATE>-00000/ exists -- more
# reliable than checking for any archived history file, since a run killed
# partway through can still have written/archived an h0 file.
assert STOP_OPTION == "ndays", "completion-date math below assumes STOP_OPTION=ndays"
_ref_y, _ref_m, _ref_d = (int(x) for x in REF_DATE.split("-"))
EXPECTED_COMPLETION_DATE = (date(_ref_y, _ref_m, _ref_d) + timedelta(days=int(STOP_N))).strftime("%Y-%m-%d")

# CTL's case.run walltime (01:45:00, see OAT.sh) was sized for a 3-month
# spin-up; these clones only run 5 days, so case.run is knocked down to
# 00:30:00 to match (case.st_archive is left at whatever CTL/create_clone
# set it to).
CASE_RUN_WALLCLOCK = "00:15:00"

BOUND_SUFFIX = {"low": "L", "high": "H"}

# The unperturbed 5-day control: same branch-off-CTL setup as every L/H
# run (same REF_DATE/STOP_N/STOP_OPTION), just with no namelist parameter
# override. Added 2026-08-10 as a fair "base" comparison point for
# generate_oat_summary.py, replacing CTL's 3-month spin-up mean (which was
# making nearly every parameter's Low/High land on the same side of base
# -- a seasonal-mean-vs-5-day-window mismatch, not a real parameter
# effect; see that day's conversation).
BASE_EXP = "MMPPE_OAT_base"
BASE_CASEROOT = os.path.join(EXPERIMENTS_DIR, BASE_EXP)


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


def is_completed(exp: str) -> bool:
    """True if `exp` has a restart archived at EXPECTED_COMPLETION_DATE,
    i.e. its 5-day run finished, regardless of whether its caseroot under
    EXPERIMENTS_DIR still exists."""
    rest_dir = os.path.join(ARCHIVE_ROOT, exp, "rest", f"{EXPECTED_COMPLETION_DATE}-00000")
    return os.path.isdir(rest_dir)


def write_status_file(table: dict[str, dict], path: str = STATUS_FILE) -> None:
    """(Re)write the completion-status CSV for every parameter in `table`
    (not just the ones requested on this invocation), based on current
    archive state. One row per parameter, one status column per bound."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["protocol_name", "category", "low_status", "high_status"])
        for name, row in table.items():
            statuses = []
            for bound in ("low", "high"):
                exp = f"MMPPE_OAT_{name}_{BOUND_SUFFIX[bound]}"
                statuses.append("complete" if is_completed(exp) else "incomplete")
            writer.writerow([name, row["category"], statuses[0], statuses[1]])
    print(f"\nWrote status for {len(table)} parameters -> {path}")


def apply_branch_xmlchanges(caseroot: str, dry_run: bool) -> None:
    """The env_run.xml + walltime changes shared by every 5-day branch off
    CTL's restart -- both the L/H parameter runs (create_one) and the
    unperturbed base run (create_base)."""
    xmlchanges = {
        "CONTINUE_RUN": "FALSE",
        "RUN_TYPE": "branch",
        "RUN_REFCASE": CTL_EXP,
        "RUN_REFDATE": REF_DATE,
        "RUN_REFDIR": REF_DIR,
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

    # Needs --subgroup (JOB_WALLCLOCK_TIME is per-job-type), so it can't go
    # in the flat xmlchanges dict above -- see OAT.sh for the same pattern.
    run(
        ["./xmlchange", f"JOB_WALLCLOCK_TIME={CASE_RUN_WALLCLOCK}", "--subgroup", "case.run"],
        cwd=caseroot,
        dry_run=dry_run,
    )


def create_base(dry_run: bool) -> None:
    """Prepare (create_clone + xmlchange only -- deliberately NOT built or
    submitted) the unperturbed 5-day base/control run: identical branch
    setup to every L/H run, off the same CTL restart, just with no
    namelist parameter override. Since it's a plain clone of CTL_CASEROOT,
    it inherits CTL's user_nl_cam as-is (same fincl/history-field config
    the L/H runs also inherit) -- nothing else to change."""
    print(f"\n[base] -> {BASE_EXP}")

    if is_completed(BASE_EXP):
        print(f"    [skip] already completed: {ARCHIVE_ROOT}/{BASE_EXP}/rest/{EXPECTED_COMPLETION_DATE}-00000/")
        return

    if os.path.isdir(BASE_CASEROOT):
        print(f"    [skip] case directory already exists: {BASE_CASEROOT}")
        return

    run(
        ["./create_clone", "--case", BASE_CASEROOT, "--clone", CTL_CASEROOT, "--keepexe"],
        cwd=SCRIPTDIR,
        dry_run=dry_run,
    )
    apply_branch_xmlchanges(BASE_CASEROOT, dry_run)

    print(
        f"    -> prepared {BASE_EXP} (NOT built or submitted -- no parameter "
        "override, this is the unperturbed control). To finish:\n"
        f"       cd {BASE_CASEROOT}\n"
        "       ./case.build --skip-provenance-check\n"
        "       ./case.submit"
    )


def create_one(protocol_name: str, row: dict, bound: str, dry_run: bool) -> None:
    value = row["low_value"] if bound == "low" else row["high_value"]
    suffix = BOUND_SUFFIX[bound]
    exp = f"MMPPE_OAT_{protocol_name}_{suffix}"
    caseroot = os.path.join(EXPERIMENTS_DIR, exp)

    print(f"\n[{protocol_name} / {bound}] -> {exp}")

    if is_completed(exp):
        print(f"    [skip] already completed: {ARCHIVE_ROOT}/{exp}/rest/{EXPECTED_COMPLETION_DATE}-00000/")
        return

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
    apply_branch_xmlchanges(caseroot, dry_run)

    append_user_nl_cam(caseroot, namelist_vars, value, dry_run)

    #run(["qcmd", "-A", PROJECTCODE, "--", "./case.build", "--skip-provenance-check"],
    run(["./case.build", "--skip-provenance-check"],
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
    parser.add_argument(
        "--status-only", action="store_true",
        help=f"just (re)write {STATUS_FILE} from current archive state, without creating/submitting any cases",
    )
    parser.add_argument(
        "--base", action="store_true",
        help=f"prepare the unperturbed 5-day base/control run ({BASE_EXP}) -- create_clone + "
             "xmlchange only, deliberately NOT built or submitted -- then exit",
    )
    args = parser.parse_args()

    table = load_param_table(args.params_file)

    if args.list:
        for name, row in table.items():
            print(f"  {name:28s} ({row['category']:11s}) -> {row['namelist_vars']}")
        return 0

    if args.status_only:
        write_status_file(table)
        return 0

    if args.base:
        create_base(args.dry_run)
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

    if not args.dry_run:
        write_status_file(table)

    return 0


if __name__ == "__main__":
    sys.exit(main())
