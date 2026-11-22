A claim result that arrives for a shop after its turn is over can make another shop lose its turn.
With three backlogged shops a, b and c in the deficit round robin: a's turn ends and b's comes next,
and then a late result for a's claim reports that a has no runnable jobs. The scheduler drops a, as
it should, but the next offer goes to c and b is skipped for the whole round. If b's turn had
already started when the late result came in, the next offer goes to c with an allowance of 0.
I expected b to keep its turn either way.
