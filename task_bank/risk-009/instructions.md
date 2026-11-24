`make paysim-rules` (`python -m ml.paysim_rules`) picks a factor that stops too many transfers. On
our PaySim copy its report says the rule file holds or blocks at most 1% of the training days'
transfers, but when we load the rule file it wrote and evaluate it on those same transfers, it
stops well over 1% of them. The report's sentence about the factor one below the chosen one gives
a count that doesn't match what that factor stops either. I expected the factor to be the
smallest one at which at most 1% of the training days' transfers are stopped, and the report's
numbers to agree with the rule file.
