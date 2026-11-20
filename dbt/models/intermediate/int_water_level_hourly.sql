-- One water level per gauge per hour. Verified values win; where NOAA has not verified
-- an hour yet, use the preliminary 6-minute reading taken exactly on the hour (that is
-- how NOAA defines its hourly height, so the two line up).
with verified as (
    select station_id, time_utc, water_level_m, true as is_verified from {{ ref('stg_tide_hourly') }}
),
preliminary as (
    select station_id, time_utc, water_level_m, false as is_verified
    from {{ ref('stg_tide_6min') }}
    where extract(minute from time_utc) = 0 and not (flag_flat or flag_rate or flag_limit)
)
select * from verified
union all
select p.* from preliminary p
anti join verified v using (station_id, time_utc)
