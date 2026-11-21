Shops that are briefly unable to claim lose their place in the scheduler's round robin and the
credit they had saved up.

With the DRR scheduler, a shop that still has jobs but can't claim at the moment (it is at its
concurrency cap, out of tokens, or throttled) is supposed to be skipped until it can claim again,
keeping both its deficit and its place in the round-robin order. Instead, once it can claim
again, the shops that were behind it get their turns first, and when its turn comes it is offered
only a fresh quantum: whatever it had left over from its previous turn is gone.

For example, take four shops that all have jobs and equal weights, where the second shop has
part of its deficit left over from its last turn. Just before its next turn, it is at its
concurrency cap at one refresh and below the cap again at the next. I expect the second shop to
be offered next, with its leftover plus a quantum. Instead the third and fourth shops are served
first, and the second shop's turn is offered a single quantum.
