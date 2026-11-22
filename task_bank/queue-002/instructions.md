`admission.RetryAfterSeconds` tells a shop that hit its backlog limit how long to wait before
retrying, and it asks for too little. A shop whose `backlog_retry_after_ms` is 1500 gets a 429
with `Retry-After: 1`, so its clients come back half a second early and are refused again. I
expected `Retry-After: 2`: a whole number of seconds that never ends before the shop's delay does.
