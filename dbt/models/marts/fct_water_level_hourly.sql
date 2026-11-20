-- The core tide table: observed vs predicted water level for every gauge and hour since
-- 2016. "Residual" = observed - predicted: the part of the water level the tide tables
-- did not expect. Storm surge, swells, and the slow rise of the sea all show up here.
with wl as (select * from {{ ref('int_water_level_hourly') }})
select
    {{ dbt_utils_surrogate_key(['wl.station_id', 'wl.time_utc']) }} as water_level_id,
    wl.station_id,
    s.name                                                as station_name,
    s.island,
    wl.time_utc,
    wl.water_level_m,
    p.predicted_m,
    round(wl.water_level_m - p.predicted_m, 3)            as residual_m,
    t.water_temp_c,
    wl.is_verified,
    s.minor_flood_m,
    wl.water_level_m >= s.minor_flood_m                   as above_minor_flood
from wl
join {{ ref('stg_tide_stations') }} s using (station_id)
left join {{ ref('stg_tide_predictions') }} p using (station_id, time_utc)
left join {{ ref('stg_water_temp') }} t using (station_id, time_utc)
