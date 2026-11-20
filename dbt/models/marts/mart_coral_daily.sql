-- Daily heat stress with the alert level spelled out. Regional rows carry only the
-- 7-day maximum alert, so that is the level we use everywhere for consistency.
select
    c.station_id,
    st.name                                   as station_name,
    st.island,
    st.kind,
    c.obs_date,
    c.sst_c,
    c.ssta_c,
    c.hotspot_c,
    c.dhw,
    c.mmm_c,
    c.baa,
    c.baa_7day_max                            as alert_level,
    b.label                                   as alert_label,
    b.short_label                             as alert_short
from {{ ref('stg_coral_daily') }} c
join {{ ref('stations') }} st on st.station_id = c.station_id
left join {{ ref('bleaching_levels') }} b on b.baa = c.baa_7day_max
