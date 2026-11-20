-- Is each feed still delivering? Compares the newest value in the warehouse with how
-- often that feed normally updates (seed feed_expectations). This is different from
-- "did the collector run": a request can succeed and still return nothing new, as the
-- buoy has done since July 2026.
with latest as (
    select 'tide_6min' as feed, station_id, max(time_utc) as latest_at from {{ ref('stg_tide_6min') }} group by 2
    union all select 'water_temp', station_id, max(time_utc) from {{ ref('stg_water_temp') }} group by 2
    union all select 'tide_verified', station_id, max(time_utc) from {{ ref('stg_tide_hourly') }} group by 2
    -- coral values are dated to the day; count the day as ending at 23:59 UTC
    union all select 'coral_daily', station_id, max(obs_date)::timestamptz + interval 1 day from {{ ref('stg_coral_daily') }} group by 2
    union all select 'buoy_waves', station_id, max(time_utc) from {{ ref('stg_buoy_waves') }} group by 2
    union all select 'buoy_ocean', station_id, max(time_utc) from {{ ref('stg_buoy_ocean') }} group by 2
),
run as (select max(last_attempt) as checked_at from {{ ref('stg_source_health') }})
select
    l.feed,
    e.dataset,
    l.station_id,
    st.name                                                         as station_name,
    l.latest_at,
    run.checked_at,
    round(date_diff('minute', l.latest_at, run.checked_at) / 60.0, 1) as age_hours,
    e.max_age_hours,
    date_diff('minute', l.latest_at, run.checked_at) / 60.0 > e.max_age_hours as is_stale,
    e.meaning
from latest l
cross join run
join {{ ref('feed_expectations') }} e using (feed)
join {{ ref('stations') }} st on st.station_id = l.station_id
