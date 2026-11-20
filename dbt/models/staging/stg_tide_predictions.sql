select cast(station as varchar) as station_id, time_utc, value as predicted_m
from {{ source('raw', 'tide_predictions') }}
