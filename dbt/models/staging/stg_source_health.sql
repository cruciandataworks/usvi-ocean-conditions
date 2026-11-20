select source, feed, source || ':' || feed as feed_key, last_attempt, last_success, consecutive_failures,
       nullif(last_error, '') as last_error, nullif(detail, '') as detail
from {{ source('raw', 'source_health') }}
