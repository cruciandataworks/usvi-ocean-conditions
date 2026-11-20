-- What the tide chart draws: the last 10 days of 6-minute readings next to the hourly
-- prediction, plus predictions for the next 3 days. "Now" is the newest reading.
with now_ as (select max(time_utc) as t from {{ ref('stg_tide_6min') }}),
obs as (
    select station_id, time_utc, water_level_m, null::double as predicted_m
    from {{ ref('stg_tide_6min') }}, now_
    where time_utc >= now_.t - interval 10 day and not (flag_flat or flag_rate or flag_limit)
),
pred as (
    select station_id, time_utc, null::double as water_level_m, predicted_m
    from {{ ref('stg_tide_predictions') }}, now_
    where time_utc between now_.t - interval 10 day and now_.t + interval 3 day
)
select station_id, time_utc, max(water_level_m) as water_level_m, max(predicted_m) as predicted_m
from (select * from obs union all select * from pred)
group by 1, 2
