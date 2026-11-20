select cast(station as varchar) as station_id, time_utc, value as water_level_m
from {{ source('raw', 'tide_hourly') }}
