When we raise a shop's `rate_per_sec`, the dispatcher lets that shop claim more jobs than its
rate limit allows. A shop at 1 job a second with a burst of 3 used up its burst; one second later
its rate was raised to 50, and on the next refresh it could claim 3 jobs at once, as if it had been
running at 50 a second all along. It should only have had the 1 token it earned at the old rate.
