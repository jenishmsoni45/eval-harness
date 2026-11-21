A payment made exactly one hour before a risk decision is missing from that decision's one-hour
features. When I call `features_at` for a decision at time `t` with one outgoing payment at
`t - 1 hour`, I expect `out_count_1h` to be 1 and `out_sum_1h` to be the payment's amount, but
both come back as 0. A payment one millisecond later than that is counted as expected.
