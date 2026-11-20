-- Turn NOAA's flood levels (heights above the station's own zero) into metres above
-- MHHW, the same reference as the water levels. Where NOAA publishes no minor flood
-- level, use its national high-tide-flooding rule (see dbt_project.yml vars).
select
    s.station_id,
    s.name,
    s.island,
    s.lat,
    s.lon,
    r.datum_epoch,
    r.great_diurnal_range_m,
    round(r.mhhw_stnd_m - r.msl_stnd_m, 3)                         as mhhw_above_msl_m,
    round(coalesce(r.nos_minor_stnd_m - r.mhhw_stnd_m,
                   {{ var('htf_range_factor') }} * r.great_diurnal_range_m + {{ var('htf_offset_m') }}), 3)
                                                                    as minor_flood_m,
    round(r.nos_moderate_stnd_m - r.mhhw_stnd_m, 3)                as moderate_flood_m,
    round(r.nos_major_stnd_m - r.mhhw_stnd_m, 3)                   as major_flood_m,
    case when r.nos_minor_stnd_m is not null then 'NOAA published'
         else 'NOAA national rule (0.04 x range + 0.50 m)' end    as minor_flood_source
from {{ ref('stations') }} s
join {{ source('raw', 'tide_stations') }} r on r.station = cast(s.station_id as varchar)
where s.kind = 'tide_gauge'
