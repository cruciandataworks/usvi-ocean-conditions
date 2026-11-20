-- Where NOAA publishes a minor flood level (Charlotte Amalie, Lime Tree Bay), it should
-- agree with NOAA's national rule within 3 cm. If it does, using the rule at the two
-- gauges without a published level is justified.
select station_id, minor_flood_m,
       round({{ var('htf_range_factor') }} * great_diurnal_range_m + {{ var('htf_offset_m') }}, 3) as rule_m
from {{ ref('stg_tide_stations') }}
where minor_flood_source = 'NOAA published'
  and abs(minor_flood_m - ({{ var('htf_range_factor') }} * great_diurnal_range_m + {{ var('htf_offset_m') }})) > 0.03
