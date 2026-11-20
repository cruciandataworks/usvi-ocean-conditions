-- One row per station and year: peak heat stress, and how many days reefs spent at
-- Alert Level 1 or above (DHW 4+: bleaching likely) and Alert Level 2+ (DHW 8+: severe).
select
    station_id,
    station_name,
    extract(year from obs_date)                                 as year,
    round(max(dhw), 2)                                          as max_dhw,
    round(max(sst_c), 2)                                        as max_sst_c,
    max(alert_level)                                            as max_alert_level,
    sum(case when alert_level >= 3 then 1 else 0 end)           as days_alert_1_plus,
    sum(case when alert_level >= 4 then 1 else 0 end)           as days_alert_2_plus,
    count(*)                                                    as days
from {{ ref('mart_coral_daily') }}
group by all
