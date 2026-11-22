Loading a PaySim file gives some transfers one cent more than the file's amount. A CASH_OUT row
with the amount 12.345 loads as a transfer of 1235 cents, but half a cent should round to the even
cent, as the loader's documentation says, so I expected 1234. Rows of half a cent are loaded as
1-cent transfers instead of being skipped as zero.
