The review capacity lets us hold one transfer in a hundred, but the model's threshold holds one
transfer fewer than that. With 300 transfers that all have different scores, `capacity(300)` is 3,
so I expected `held(scores, threshold_for(scores, 3))` to hold the 3 highest-scoring transfers. It
holds only the top 2.
