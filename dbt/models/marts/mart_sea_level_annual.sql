-- Yearly mean water level relative to mean sea level of NOAA's 1983-2001 "epoch".
-- The tide tables (and MHHW) are tied to that epoch, so a rising sea shows up as a
-- yearly mean that keeps climbing above zero. Only years with 90% of hours count.
select
    f.station_id,
    f.station_name,
    extract(year from f.time_utc)                                  as year,
    count(*)                                                       as hours,
    round(avg(f.water_level_m) + s.mhhw_above_msl_m, 3)            as mean_above_epoch_msl_m,
    round(avg(f.residual_m), 3)                                    as mean_residual_m,
    sum(case when f.above_minor_flood then 1 else 0 end)           as hours_above_minor_flood,
    count(*) >= 0.9 * 24 * 365                                     as is_complete_year
from {{ ref('fct_water_level_hourly') }} f
join {{ ref('stg_tide_stations') }} s using (station_id)
group by f.station_id, f.station_name, extract(year from f.time_utc), s.mhhw_above_msl_m
