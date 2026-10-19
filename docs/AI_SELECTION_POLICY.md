# AI clip-selection policy

Qwen's structured `keep` decision is required before a Qwen-scored candidate can
be rendered. A structured `reject` is final for that candidate; sentence-boundary
and duration checks refine approved clips and do not overrule editorial rejection.
If every valid Qwen decision is `reject`, the job produces no Short and reports
that result instead of silently switching to deterministic ranking.

Malformed candidates (missing or unknown decisions, invalid score dimensions, or
unexpected IDs) are not treated as approvals. Missing candidate responses receive
the existing bounded individual retry. Deterministic ranking is used only when
there are no valid structured Qwen scores at all, and the resulting Short metadata
and UI label it as a fallback. There is no retry loop after a valid Qwen decision.
