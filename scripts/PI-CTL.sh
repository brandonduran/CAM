#!/bin/bash
#set -e
script_name=OAT.sh

# ==============================================================================
# MMPPE control run (CTL): 3-month spin-up ending July 31 2025, from which
# the OAT parameter_L/parameter_H 5-day runs will branch (see
# MMPPE-info/MMPPE.md "One-At-a-Time Test" and MMPPE-info/OAT-READ.md).
# Modeled on the ~/LaunchScripts/wildfires/*.txt pattern (PDstandard.txt /
# wildfiresPIwNL.txt), adapted for this clean-CAM/MMPPE-ACI setup.
# ==============================================================================

##### USER CHANGE ################################################
EXP="MMPPE_PI_CTL"

# TODO (not yet decided): which CIME checkout has clean-CAM wired in as its
# 'cam' external? SCRIPTDIR must point at that checkout's cime/scripts dir
# before this script will run -- see the wildfires scripts for the pattern
# (each of those points at a DIFFERENT cime checkout, e.g.
# /glade/work/bduran/cam-for-wildfires/cime/scripts); none of them already
# point at clean-CAM, so this needs to be set up or identified first.
SCRIPTDIR="/glade/work/bduran/clean-CAM/cime/scripts"

COMPSET="F2000climo"

RES="f09_f09_mg17"
MACH="derecho"            # matches every one of the wildfires reference scripts
PROJECTCODE="UCSD0085"
SUBMIT="true"
BUILD="true"
PREVIEW="true"
EMAIL="bmduran@ucsd.edu"  # matches the wildfires scripts' convention; change if wrong
##################################################################

if [[ -z "$SCRIPTDIR" || -z "$COMPSET" ]]; then
    echo "ERROR: SCRIPTDIR and COMPSET must be set before running this script -- see the TODO comments above."
    exit 1
fi

cd $SCRIPTDIR
if [ $(pwd) != $SCRIPTDIR ]
then echo "SY_ERROR: Make sure your SCRIPTDIR/SRCDIR is set correctly in the batch
script."
exit
fi

CASEROOT=/glade/work/bduran/MMPPE-ACI/$EXP

# Create a new case
cd $SCRIPTDIR
./create_newcase --case $CASEROOT --res $RES --compset $COMPSET --machine $MACH --project $PROJECTCODE --run-unsupported

cd $CASEROOT

./case.setup --clean

# PE layout: 512 tasks, per this repo's own PFS_comparison_summary.txt
# benchmark for f09_f09_mg17.F1850 on derecho -- 512 PEs scales at ~96.5%
# efficiency vs. 256 (nearly 2x throughput for ~3.5% more core-hours).
# Revisit if a different resolution/compset changes the cost/throughput
# tradeoff.
./xmlchange NTASKS=512
./xmlchange NTASKS_ESP=1

# Change env_run.xml
./xmlchange --file env_run.xml --id CONTINUE_RUN --val FALSE
./xmlchange --file env_run.xml --id RUN_TYPE --val startup
./xmlchange --file env_run.xml --id GET_REFCASE --val FALSE

# For control run spin up of 3 months, to end at July 31st
# Then branch for 5 days for OAT, will have in future scripts
./xmlchange RUN_STARTDATE=2024-07-01
./xmlchange STOP_N=3
./xmlchange STOP_OPTION=nmonths
./xmlchange REST_N=3
./xmlchange REST_OPTION=nmonths
./xmlchange RESUBMIT=5

# SST/sea-ice forcing: our own ERA5-derived, f09-regridded, CAM bndtvs-format
# boundary dataset (see forcing_datasets/regrid_sst_ice_to_f09.py and
# ppe_changes_incorporated.txt). Using the extended file (1999-2027, with
# Jul-Dec 2026 and all of 2027 synthetically filled per
# forcing_datasets/readme.md) rather than the shorter all-real 2024-2025
# file, since that was already your choice in the original draft of this
# script -- the 2025 portion used here is real ERA5 data either way.
./xmlchange SSTICE_DATA_FILENAME=/glade/work/bduran/clean-CAM/forcing_datasets/regridded/era5_sst_sic_1999_2027_extended_filled_0.9x1.25.nc
# TODO: SSTICE_YEAR_ALIGN/START/END tell CIME how to index into a
# multi-year transient SST file -- almost certainly needed (without them
# above. Likely values for this run: all three = 2025.
./xmlchange SSTICE_YEAR_ALIGN=2024
./xmlchange SSTICE_YEAR_START=2024
./xmlchange SSTICE_YEAR_END=2025

./xmlchange --append CAM_CONFIG_OPTS="-cosp"

# Configure case
./case.setup

## user_nl_cam: OAT "Variables to test" history output, GHG values, and
## nudging config already built for this run -- see MMPPE-info/user_nl_cam
## (MMPPE-info/OAT_variable_mapping.txt documents the field choices;
## ppe_changes_incorporated.txt documents the new diagnostic fields it
## requests, e.g. ANGSTRM_550_865, CCN7COL, the ACT*_OVL comparison fields).
cat /glade/work/bduran/clean-CAM/MMPPE-info/user_nl_cam_PI >> user_nl_cam

# Copying this current launch script for record
cp /glade/work/bduran/clean-CAM/scripts/$script_name $CASEROOT

# Run-specific edits
./xmlchange --file env_run.xml --id JOB_PRIORITY --val regular

# Build run
./case.build --clean-all
if [[ "$PREVIEW" == "true" ]]; then
   echo "-------------------- Previewing ${EXP} ------------------------"
   ./preview_run
   ./preview_namelists
fi

echo "----------------------- Building ${EXP} --------------------------"
if [[ "$BUILD" == "true" ]]; then

   ./case.build --skip-provenance-check

   cd $CASEROOT

   # Run-specific edits
   sed -i '10i #PBS  -m abe' .case.run
   sed -i "11i #PBS  -M $EMAIL" .case.run
fi

# Submit run
if [[ "$SUBMIT" == "true" ]] ; then
    ./case.submit
fi

echo "----------------------- ${EXP} is submitted --------------------------"

# NOTE for documenting this case
cat <<EOF >> $CASEROOT/README.case
---------------------------------
USER NOTE (by $USER  --  $(date))
---------------------------------

MMPPE PI 3-month control run (CTL)

Compset: $COMPSET
Resolution: $RES
Machine: $MACH

Note:
3-month spin-up (2024-07-01 through 2024-09-31) of the PI MMPPE
state. No PPE parameters perturbed in this run. Resubmit of 5
to run full extent.
EOF
