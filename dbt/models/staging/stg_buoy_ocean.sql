select station as station_id, time_utc, water_temp_c, salinity_psu, qc_flag
from {{ source('raw', 'buoy_ocean') }}
where qc_flag in (1, 2) and water_temp_c is not null
