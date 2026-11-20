-- QARTOD flags: 1 pass, 2 not evaluated, 3 suspect, 4 fail, 9 missing. Keep 1 and 2.
select station as station_id, time_utc, wave_height_m, max_wave_height_m, wave_period_s, wave_direction_deg, qc_flag
from {{ source('raw', 'buoy_waves') }}
where qc_flag in (1, 2) and wave_height_m is not null
