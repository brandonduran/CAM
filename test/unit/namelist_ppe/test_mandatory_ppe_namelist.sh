#!/usr/bin/env bash
#
# test_mandatory_ppe_namelist.sh
#
# Namelist-registration test for the MMPPE "mandatory 21" parameters
# (see MMPPE-info/MMPPE.md). This does NOT compile or run CAM -- it drives
# the legacy standalone bld/configure + bld/build-namelist scripts to
# confirm each parameter's namelist variable(s):
#   1. are accepted by build-namelist (i.e. registered in
#      namelist_definition.xml with a default in namelist_defaults_cam.xml
#      and an add_default() call in build-namelist), and
#   2. round-trip to the requested value in the generated atm_in file.
#
# It also runs one negative control (an unregistered variable name) to
# prove the harness actually detects a real registration failure, and
# checks the 4 deferred parameters (rad_bc_ni, rad_oc_ni, emi_cmr_ff,
# emi_cmr_bb) are correctly reported as NOT YET IMPLEMENTED.
#
# Usage:
#   test_mandatory_ppe_namelist.sh [-csmdata <inputdata_root>] [-keep]
#
# Requires: perl, and read access to a CESM inputdata root (for -csmdata;
# defaults to the NCAR/CISL shared inputdata mount).

set -u

CAM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CSMDATA="/glade/campaign/cesm/cesmdata/cseg/inputdata"
KEEP=0

while [ $# -gt 0 ]; do
    case "$1" in
        -csmdata) CSMDATA="$2"; shift 2 ;;
        -keep)    KEEP=1; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/ppe_nl_test.XXXXXX")"
cleanup() {
    if [ "$KEEP" -eq 0 ]; then
        rm -rf "$WORKDIR"
    else
        echo "Work directory kept at: $WORKDIR"
    fi
}
trap cleanup EXIT

echo "CAM root:    $CAM_ROOT"
echo "csmdata:     $CSMDATA"
echo "Work dir:    $WORKDIR"
echo

# --- Set up a minimal standalone-build tree ---------------------------------
# bld/configure infers cam_root from its own location and requires either
# a components/cam/src (CESM checkout) or src (standalone checkout) layout,
# plus a cime/ directory to pick the standalone branch. We symlink bld and
# src from the real checkout and use an empty cime/ marker dir (-ccsm_seq
# skips the MCT library build that would otherwise require real cime
# content).
ln -s "$CAM_ROOT/bld" "$WORKDIR/bld"
ln -s "$CAM_ROOT/src" "$WORKDIR/src"
mkdir -p "$WORKDIR/cime"

cd "$WORKDIR" || exit 1

echo "Running configure..."
if ! perl "$WORKDIR/bld/configure" -s -ccsm_seq > configure.log 2>&1; then
    echo "FAIL: configure did not complete successfully. See $WORKDIR/configure.log"
    KEEP=1
    exit 1
fi
echo "configure OK (CAM6 defaults: dyn=fv, chem=trop_mam4)"
echo

# --- Test-case table ---------------------------------------------------------
# Format: "protocol_name|namelist_var1=value1[,namelist_var2=value2...]"
# One or more namelist variables may map to a single protocol parameter.
declare -a CASES=(
  "emi_ant_so2|srf_emis_scale_so2_ant=1.5"
  "emi_ant_bc|srf_emis_scale_bc_ant=1.5"
  "emi_ant_oc|srf_emis_scale_oc_ant=1.5"
  "emi_bb_so2|srf_emis_scale_so2_bb=1.5"
  "emi_bb_bc|srf_emis_scale_bc_bb=1.5"
  "emi_bb_oc|srf_emis_scale_oc_bb=1.5"
  "emi_dms|srf_emis_scale_dms=1.5"
  "emi_ss_acc|seasalt_emis_scale_accum=1.5"
  "emi_ss_coa|seasalt_emis_scale_coarse=1.5"
  "emi_du|dust_emis_fact=0.5"
  "wetdep_ic|sol_facti_cloud_borne=0.8"
  "activ_aero|microp_aero_npccn_scale=1.3"
  "activ_cwturb|microp_aero_wsub_scale=1.3,microp_aero_wsubi_scale=1.3"
  "micro_ccraut|micro_mg_autocon_fact=0.02"
  "micro_ccsaut|micro_mg_iautocon_fact=1.5"
  "conv_cprcon|zmconv_c0_lnd=0.01,zmconv_c0_ocn=0.01"
  "conv_entrpen|zmconv_dmpdz=-2.0e-3"
)

# Deferred parameters: expected to NOT be registered yet.
declare -a DEFERRED=(
  "emi_cmr_ff|emi_cmr_ff=30.0"
  "emi_cmr_bb|emi_cmr_bb=75.0"
  "rad_bc_ni|rad_bc_ni=0.71"
  "rad_oc_ni|rad_oc_ni=0.0055"
)

NPASS=0
NFAIL=0
FAILED_NAMES=()

run_case() {
    local label="$1" varlist="$2"
    local nlvars="" fld var val

    IFS=',' read -ra pairs <<< "$varlist"
    nlvars="&camexp"$'\n'
    for fld in "${pairs[@]}"; do
        var="${fld%%=*}"
        val="${fld#*=}"
        nlvars+=" ${var} = ${val}"$'\n'
    done
    nlvars+="/"

    rm -f "$WORKDIR/atm_in" "$WORKDIR/drv_flds_in"
    local out
    out=$(perl "$WORKDIR/bld/build-namelist" -s -config "$WORKDIR/config_cache.xml" \
          -csmdata "$CSMDATA" -namelist "$nlvars" 2>&1)
    local rc=$?

    if [ $rc -ne 0 ]; then
        echo "  build-namelist error:"
        echo "$out" | sed 's/^/    /'
        return 1
    fi

    for fld in "${pairs[@]}"; do
        var="${fld%%=*}"
        val="${fld#*=}"
        local got
        got=$(grep -E "^\s*${var}\s*=" "$WORKDIR/atm_in" | head -1)
        if [ -z "$got" ]; then
            echo "  $var: NOT FOUND in atm_in"
            return 1
        fi
        # normalize whitespace/case for comparison (D0 vs no exponent etc. tolerated loosely)
        if ! echo "$got" | grep -qF -- "$val"; then
            echo "  $var: expected '$val', got: $got"
            return 1
        fi
        echo "  $var = $got"
    done
    return 0
}

echo "=== Mandatory PPE parameters: implemented (17) ==="
for c in "${CASES[@]}"; do
    label="${c%%|*}"
    varlist="${c#*|}"
    echo "-- $label ($varlist) --"
    if run_case "$label" "$varlist"; then
        echo "  PASS"
        NPASS=$((NPASS+1))
    else
        echo "  FAIL"
        NFAIL=$((NFAIL+1))
        FAILED_NAMES+=("$label")
    fi
    echo
done

echo "=== Deferred parameters: expected NOT registered (4) ==="
NDEFER_OK=0
NDEFER_UNEXPECTED=0
for c in "${DEFERRED[@]}"; do
    label="${c%%|*}"
    varlist="${c#*|}"
    var="${varlist%%=*}"
    val="${varlist#*=}"
    rm -f "$WORKDIR/atm_in" "$WORKDIR/drv_flds_in"
    out=$(perl "$WORKDIR/bld/build-namelist" -s -config "$WORKDIR/config_cache.xml" \
          -csmdata "$CSMDATA" -namelist "&camexp
 ${var} = ${val}
/" 2>&1)
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "-- $label ($var): correctly NOT registered (build-namelist rejected it)"
        NDEFER_OK=$((NDEFER_OK+1))
    else
        echo "-- $label ($var): UNEXPECTED -- build-namelist accepted a variable that should not exist yet!"
        NDEFER_UNEXPECTED=$((NDEFER_UNEXPECTED+1))
    fi
done
echo

echo "=== Negative control: unregistered variable name ==="
out=$(perl "$WORKDIR/bld/build-namelist" -s -config "$WORKDIR/config_cache.xml" \
      -csmdata "$CSMDATA" -namelist "&camexp
 this_variable_does_not_exist_ppe_test = 1.0
/" 2>&1)
rc=$?
if [ $rc -ne 0 ]; then
    echo "PASS: build-namelist correctly rejected an unregistered variable name"
    NEGCTRL_OK=1
else
    echo "FAIL: build-namelist silently accepted an unregistered variable name -- test harness cannot be trusted!"
    NEGCTRL_OK=0
fi
echo

echo "============================================================"
echo "SUMMARY"
echo "============================================================"
echo "Implemented mandatory params: $NPASS/$((NPASS+NFAIL)) passed"
if [ $NFAIL -gt 0 ]; then
    echo "  Failed: ${FAILED_NAMES[*]}"
fi
echo "Deferred params correctly unregistered: $NDEFER_OK/4"
if [ "$NDEFER_UNEXPECTED" -gt 0 ]; then
    echo "  WARNING: $NDEFER_UNEXPECTED deferred param(s) unexpectedly registered -- update this test's DEFERRED list."
fi
echo "Negative control (harness sanity check): $([ "$NEGCTRL_OK" -eq 1 ] && echo PASS || echo FAIL)"
echo

if [ $NFAIL -gt 0 ] || [ "$NEGCTRL_OK" -ne 1 ]; then
    exit 1
fi
exit 0
