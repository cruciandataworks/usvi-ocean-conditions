-- 6-minute water level. NOAA's quality letter: p = preliminary (automated checks only),
-- v = verified by an analyst. Flags are four 0/1 digits; we keep the ones that matter.
select
    cast(station as varchar)                 as station_id,
    time_utc,
    value                                    as water_level_m,
    sigma                                    as sigma_m,
    quality,
    split_part(flags, ',', 2) = '1'          as flag_flat,        -- value stuck (sensor issue)
    split_part(flags, ',', 3) = '1'          as flag_rate,        -- changed implausibly fast
    split_part(flags, ',', 4) = '1'          as flag_limit        -- outside expected max/min
from {{ source('raw', 'tide_6min') }}
