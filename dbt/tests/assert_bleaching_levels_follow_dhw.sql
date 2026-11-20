-- Recompute Coral Reef Watch's daily alert level from its own published rule and
-- compare. Rule: HotSpot <= 0 -> No stress (0); 0 < HS < 1 -> Watch (1); HS >= 1 and
-- DHW < 4 -> Warning (2); HS >= 1 and DHW 4-8, 8-12, 12-16, 16-20, 20+ -> Alert 1-5.
-- Single-pixel stations only (the regional file has no daily level). CRW works from
-- unrounded values, so a DHW printed as 7.996 can sit on either side of 8: we accept
-- the level computed from the printed value or from it rounded to one decimal.
{{ config(severity='warn') }}
{%- set ns = [] -%}
{%- for d in ['dhw', 'round(dhw, 1)'] -%}
{%- do ns.append("case when hotspot_c <= 0 then 0 when hotspot_c < 1 then 1 when " ~ d ~ " < 4 then 2 when " ~ d ~ " < 8 then 3 when " ~ d ~ " < 12 then 4 when " ~ d ~ " < 16 then 5 when " ~ d ~ " < 20 then 6 else 7 end") -%}
{%- endfor %}
select station_id, obs_date, hotspot_c, dhw, baa
from {{ ref('stg_coral_daily') }}
where baa is not null and hotspot_c is not null and dhw is not null
  and baa not in ({{ ns | join(', ') }})
