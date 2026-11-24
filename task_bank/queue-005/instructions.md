Jobs wait too long before their first retry. `queue.Backoff.Bound` gives the upper bound of the
random delay after a job's n-th failed attempt, and the design says it is the base for the first
failure, doubling with each failure after that, up to the cap. With a 500 ms base,
`Bound(1)` returns 1 s instead of 500 ms, and every later bound is twice what it should be, so the
cap is reached one failure early.
