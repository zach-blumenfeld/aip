# Revise the work

The verdicts below are in the same order as the policies. A policy failed when its verdict's
`follows.value` is `false`, or when its `follows.noul`, the probability the model put on the work
following the policy, is not above 0.7: the check counts a verdict the model was not more than
0.7 sure of as failed (`confidence` is a different number and is not the one the check reads).
`check_summary.all_hold` is `false` because at least one failed. Revise the work so every policy
passes, changing nothing else.

Task:
{task}

Work:
{work}

Policies:
{policies}

Verdicts:
{verdicts}

Check summary:
{check_summary}

Return JSON with `work` (the revised result).
