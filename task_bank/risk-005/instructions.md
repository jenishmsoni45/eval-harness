The model card's PR-AUC changes when nothing changes but the order of the transfers. Four
transfers scored 0.8 (fraud), 0.6 (fraud), 0.6 (not fraud) and 0.2 (not fraud) give a PR-AUC of
1.0, and the same four with the two 0.6 transfers listed the other way round give 0.75. Their
scores and labels are the same, so I expected the same PR-AUC both times. Shuffling the test days'
rows before computing the card's metrics moves PR-AUC in the same way whenever transfers share a
score.
