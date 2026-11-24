A transfer that fires both a hold rule and a block rule is held instead of blocked. With a rule
that holds large payments and a rule that blocks retry storms, `RuleSet.evaluate` on a transfer
that matches both returns `("hold", [...])` with both rules listed. I expected the block to win:
a block stops the money for good, and the rule file's design says the strictest action that
fires decides.
