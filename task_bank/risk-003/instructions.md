Splitting the transfers by day puts one day too many into the test set. With a month of data,
days 0 to 30, I expected the last 7 days (24 to 30) to be the test set and the 2 days before them
(22 and 23) to set the threshold, with days 0 to 21 for training. Instead the test set holds 8
days, 23 to 30, and only day 22 is left to set the threshold.
