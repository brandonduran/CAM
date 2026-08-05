
# For control run spin up of 3 months, to end at July 31st
# Then branch for 5 days for OAT, will have in future scripts
./xmlchange RUN_STARTDATE=05-01-2025
./xmlchange STOP_N=3
./xmlchange STOP_OPTION=nmonths
./xmlchange REST_N=3
./xmlchange REST_OPTION=nmonths
./xmlchange SSTICE_DATA_FILENAME=/glade/work/bduran/clean-CAM/forcing_datasets/regridded/era5_sst_sic_1999_2027_extended_filled_0.9x1.25.nc

