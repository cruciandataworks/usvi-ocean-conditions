select
    station                         as station_id,
    cast(date as date)              as obs_date,
    sst_c,
    ssta_c,
    hotspot_c,
    dhw,
    baa,
    baa_7day_max,
    mmm_c
from {{ source('raw', 'coral_daily') }}
