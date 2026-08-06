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
EXP="MMPPE_OAT_CTL"

# TODO (not yet decided): which CIME checkout has clean-CAM wired in as its
# 'cam' external? SCRIPTDIR must point at that checkout's cime/scripts dir
# before this script will run -- see the wildfires scripts for the pattern
# (each of those points at a DIFFERENT cime checkout, e.g.
# /glade/work/bduran/cam-for-wildfires/cime/scripts); none of them already
# point at clean-CAM, so this needs to be set up or identified first.
SCRIPTDIR="/glade/work/bduran/clean-CAM/cime/scripts"

# TODO (not yet decided): exact compset string. wildfires uses
# 2010_CAM60_CLM50%SP_CICE%PRES_DOCN%DOM_MOSART_SGLC_SWAV (prescribed SST
# via a DOCN%DOM data-ocean component), but MMPPE's aerosol-cloud-
# interaction focus (MAM4/MG2/ZM -- the PPE knobs this branch adds) may
# call for a different one. NOTE: if the final compset does NOT include
# DOCN%DOM (e.g. CAM reads SST directly via its own bndtvs mechanism
# instead), the SSTICE_DATA_FILENAME xmlchange below still applies (CIME
# translates it into CAM's bndtvs namelist entry either way), but you may
# also need bndtvs_domain -- see the note above the SSTICE_DATA_FILENAME
# xmlchange below.
COMPSET="F2000"

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
./xmlchange RUN_STARTDATE=2025-05-01
./xmlchange STOP_N=3
./xmlchange STOP_OPTION=nmonths
./xmlchange REST_N=3
./xmlchange REST_OPTION=nmonths
./xmlchange RESUBMIT=0

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
# the model may default to the file's first year rather than 2025), but
# left unset since whether these are DOCN-stream variables or apply
# directly to CAM's bndtvs reading depends on the still-undecided COMPSET
# above. Likely values for this run: all three = 2025.
# ./xmlchange SSTICE_YEAR_ALIGN=2025
# ./xmlchange SSTICE_YEAR_START=2025
# ./xmlchange SSTICE_YEAR_END=2025
# TODO: if the final compset has CAM read SST directly (not via DOCN%DOM),
# it will also need bndtvs_domain pointed at the matching f09 ocean domain
# file (see forcing_datasets/regrid_sst_ice_to_f09.py's DOMAIN_FILE):
# ./xmlchange --file env_run.xml --id BNDTVS_DOMAIN --val /glade/campaign/cesm/cesmdata/cseg/inputdata/share/domains/domain.ocn.fv0.9x1.25_gx1v7.151020.nc

./xmlchange --append CAM_CONFIG_OPTS="-cosp"

# Configure case
./case.setup

## user_nl_cam: OAT "Variables to test" history output, GHG values, and
## nudging config already built for this run -- see MMPPE-info/user_nl_cam
## (MMPPE-info/OAT_variable_mapping.txt documents the field choices;
## ppe_changes_incorporated.txt documents the new diagnostic fields it
## requests, e.g. ANGSTRM_550_865, CCN7COL, the ACT*_OVL comparison fields).
cat /glade/work/bduran/clean-CAM/MMPPE-info/user_nl_cam >> user_nl_cam

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

   qcmd -A $PROJECTCODE -- ./case.build --skip-provenance-check

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

MMPPE OAT control run (CTL)

Compset: $COMPSET
Resolution: $RES
Machine: $MACH

Note:
3-month spin-up (2025-05-01 through 2025-07-31) of the default MMPPE CTL
state, per MMPPE-info/MMPPE.md's One-At-a-Time Test protocol: "first
perform a 3-month spin-up of the default CTL run, then initialize all OAT
runs from this same CTL state." No PPE parameters perturbed in this run.
History output limited to the OAT "Variables to test" list (see
MMPPE-info/OAT_variable_mapping.txt, MMPPE-info/user_nl_cam).
EOF
