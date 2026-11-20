-- The tide chart shows the next three days. Every gauge must have predictions at least
-- two days past its newest observation, or the forecast part of the page goes blank.
with p as (select station_id, max(time_utc) as last_prediction from {{ ref('stg_tide_predictions') }} group by 1),
     o as (select station_id, max(time_utc) as last_observation from {{ ref('stg_tide_6min') }} group by 1)
select s.station_id, p.last_prediction, o.last_observation
from {{ ref('stg_tide_stations') }} s
left join p using (station_id)
left join o using (station_id)
where p.last_prediction is null or p.last_prediction < o.last_observation + interval 2 day
