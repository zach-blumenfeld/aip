# Revise the work

The policy check below has one answer per policy (`pii`, `claims`, `tone`, `length`). A policy
failed when its `value` is `false`, or when its `noul`, the probability the model put on the
policy holding, is not above 0.7: the check counts an answer the model was not more than 0.7
sure of as failed (`confidence` is a different number and is not the one the check reads).
`check_summary.all_hold` is `false` because at least one failed. Revise the work so the failed
policies pass, changing nothing else.

Request:
{request}

Work:
{work}

Policy check:
{policy_check}

Check summary:
{check_summary}

Policy:
{assets[policy]}

Approved claims:
{assets[claims]}

Return JSON with `work` (the revised text).
