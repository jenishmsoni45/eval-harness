Every transfer loaded from the PaySim CSV is stamped an hour late. Rows of step 1 should get times
from 2026-01-01T00:00:00Z up to 01:00:00Z, the first hour of the data, but they get times from
01:00:00Z, and the rows of step 24 land after midnight, on 2 January. The hour of day the offline
features report is one hour off in the same way. I expected each step's transfers to lie in that
step's own UTC hour, their hour of day to match, and each transfer's day in the train, threshold
and test split to be the UTC date of its time.
