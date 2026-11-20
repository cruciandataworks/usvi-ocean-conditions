-- Every condition that deserves a human's attention right now, one row each. The
-- workflow turns each row into a GitHub issue (opened when it starts, closed when it
-- clears), so alert_key must stay the same for as long as the condition lasts.
with coral_latest as (
    select * from {{ ref('mart_coral_daily') }}
    qualify row_number() over (partition by station_id order by obs_date desc) = 1
),
bleaching as (
    -- the regional station speaks for the territory; pixel stations add detail in the message
    select
        'bleaching:usvi'                                                as alert_key,
        'coral'                                                         as category,
        case when r.alert_level >= 5 then 'high' else 'medium' end      as severity,
        'Coral bleaching heat stress: ' || r.alert_label                as title,
        'NOAA Coral Reef Watch puts the Virgin Islands at ' || r.alert_label || ' on '
            || strftime(r.obs_date, '%d %b %Y') || ' with ' || round(r.dhw, 1)
            || ' degree heating weeks (bleaching likely at 4, severe at 8). Sea surface '
            || round(r.sst_c, 2) || ' C, ' || round(r.ssta_c, 2) || ' C above normal. Station range: '
            || (select string_agg(station_name || ' ' || round(dhw, 1), ', ' order by dhw desc)
                from coral_latest where kind = 'coral_pixel') || ' DHW.'   as message,
        r.obs_date::timestamptz                                         as observed_at,
        r.alert_level                                                   as level
    from coral_latest r
    where r.station_id = 'usvi' and r.alert_level >= 3
),
flood as (
    select
        'flood:' || w.station_id                                        as alert_key,
        'tide'                                                          as category,
        'high'                                                          as severity,
        'High-tide flooding at ' || s.name                              as title,
        'Water at ' || s.name || ' reached ' || round(max(w.water_level_m), 2)
            || ' m above MHHW (minor flood level ' || s.minor_flood_m || ' m) in the last 24 hours.' as message,
        max(w.time_utc)                                                 as observed_at,
        null::int                                                       as level
    from {{ ref('stg_tide_6min') }} w
    join {{ ref('stg_tide_stations') }} s using (station_id)
    where w.time_utc >= (select max(time_utc) from {{ ref('stg_tide_6min') }}) - interval 24 hour
      and w.water_level_m >= s.minor_flood_m
      and not (w.flag_flat or w.flag_rate or w.flag_limit)
    group by w.station_id, s.name, s.minor_flood_m
),
stale as (
    select
        'stale:' || feed || ':' || station_id                           as alert_key,
        'data'                                                          as category,
        'low'                                                           as severity,
        dataset || ' has stopped updating: ' || station_name            as title,
        'Newest value is from ' || strftime(latest_at, '%d %b %Y %H:%M UTC') || ', '
            || round(age_hours / 24, 1) || ' days ago. Expected within ' || max_age_hours || ' hours. '
            || meaning || '.'                                           as message,
        latest_at                                                       as observed_at,
        null::int                                                       as level
    from {{ ref('mart_feed_freshness') }}
    where is_stale
),
failing as (
    select
        'collector:' || feed_key                                        as alert_key,
        'pipeline'                                                      as category,
        'medium'                                                        as severity,
        'Collector failing: ' || feed_key                               as title,
        consecutive_failures || ' runs in a row failed. Last error: ' || coalesce(last_error, '?')
            || '. Last success: ' || coalesce(strftime(last_success, '%d %b %Y %H:%M UTC'), 'never') || '.' as message,
        last_attempt                                                    as observed_at,
        null::int                                                       as level
    from {{ ref('stg_source_health') }}
    where consecutive_failures >= {{ var('max_consecutive_failures') }}
)
select * from bleaching
union all select * from flood
union all select * from stale
union all select * from failing
