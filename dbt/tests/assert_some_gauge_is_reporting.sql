-- At least one of the four gauges must have reported in the last 12 hours of the run.
-- If none has, NOAA's service or our collector is down; the page would show old tides
-- as if current. Error severity: stop the refresh and alert.
select 1
from (select max(time_utc) as latest from {{ ref('stg_tide_6min') }}) l,
     (select max(last_attempt) as checked_at from {{ ref('stg_source_health') }} where source = 'tide') r
where l.latest < r.checked_at - interval 12 hour
