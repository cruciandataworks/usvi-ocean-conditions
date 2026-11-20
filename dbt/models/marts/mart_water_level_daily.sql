-- Daily summary per gauge (days in Atlantic Standard Time, UTC-4, the local clock).
select
    station_id,
    station_name,
    island,
    cast(time_utc - interval 4 hour as date)        as local_date,
    count(*)                                        as hours,
    round(max(water_level_m), 3)                    as max_water_level_m,
    round(avg(water_level_m), 3)                    as mean_water_level_m,
    round(max(residual_m), 3)                       as max_residual_m,
    round(avg(residual_m), 3)                       as mean_residual_m,
    round(avg(water_temp_c), 2)                     as mean_water_temp_c,
    sum(case when above_minor_flood then 1 else 0 end) as hours_above_minor_flood,
    bool_and(is_verified)                           as fully_verified
from {{ ref('fct_water_level_hourly') }}
group by all
