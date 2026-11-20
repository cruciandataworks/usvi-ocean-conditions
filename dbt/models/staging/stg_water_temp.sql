select cast(station as varchar) as station_id, time_utc, value as water_temp_c
from {{ source('raw', 'water_temp_hourly') }}
where value between 15 and 40   -- the CO-OPS feed has no QC flags; drop impossible readings
