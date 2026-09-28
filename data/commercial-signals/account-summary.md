# Account histories: tail vs control

Tail 23 accounts (15 with readable history), control 23 (16).
Hidden or unavailable histories: tail 8, control 7.

| feature | tail median | control median | tail IQR | control IQR | p (Mann-Whitney) |
|---|---|---|---|---|---|
| account_age_days | 1.66e+03 | 1.65e+03 | 946-2.21e+03 | 472-2.46e+03 | 0.906 |
| link_karma | 684 | 1.08e+03 | 184-2.09e+03 | 230-2.74e+03 | 0.782 |
| comment_karma | 1.6e+03 | 5.75e+03 | 988-4.2e+03 | 1.44e+03-1.05e+04 | 0.244 |
| n_comments_total | 1.25e+03 | 1.7e+03 | 542-1.82e+03 | 675-1.96e+03 | 0.228 |
| n_submissions_total | 29 | 68.5 | 9-66.5 | 33-100 | 0.082 |
| n_corpus_comments | 13 | 23 | 11-26 | 14.8-31.5 | 0.085 |
| share_corpus_comments_visible | 1 | 1 | 1-1 | 1-1 | 0.536 |
| history_first_comment_days_ago | 414 | 296 | 152-896 | 241-697 | 0.649 |
| share_comments_knife_subs | 0.0318 | 0.103 | 0.00889-0.216 | 0.0549-0.338 | 0.133 |
| share_comments_knife_adjacent | 0.462 | 0.35 | 0.073-0.629 | 0.119-0.744 | 0.737 |
| n_subreddits | 66 | 47 | 14-127 | 30.8-118 | 0.635 |
| top_sub_share | 0.355 | 0.352 | 0.21-0.461 | 0.212-0.482 | 0.921 |
| days_creation_to_first_knife_comment | 202 | 127 | 22-1.02e+03 | 10.8-232 | 0.386 |
| share_history_before_first_knife | 0.0722 | 0.00848 | 0.003-0.0824 | 0.00176-0.0311 | 0.228 |
| share_comments_naming_any_knife_brand | 0.0588 | 0.0333 | 0.0165-0.124 | 0.0226-0.0903 | 0.707 |
| n_distinct_knife_brands_named | 7 | 12 | 4-14 | 8-13 | 0.165 |
| share_knife_comments_in_purchase_threads | 0.134 | 0.0966 | 0.0675-0.216 | 0.0624-0.203 | 0.770 |
| share_comments_with_any_link | 0.0758 | 0.0446 | 0.0359-0.142 | 0.0246-0.11 | 0.406 |
| share_comments_with_store_link | 0.00321 | 0.00211 | 0-0.0256 | 0-0.00521 | 0.385 |
| comments_per_active_day | 3.29 | 4.64 | 2.63-6.89 | 3.12-7.39 | 0.594 |
| share_comments_in_top3_hours | 0.302 | 0.272 | 0.263-0.327 | 0.245-0.319 | 0.295 |
| median_comment_len | 140 | 107 | 76.5-158 | 86.2-145 | 0.797 |
| share_comments_scored_le1 | 0.516 | 0.435 | 0.456-0.607 | 0.385-0.596 | 0.295 |
| share_comments_as_op | 0.0618 | 0.0984 | 0.0127-0.287 | 0.0332-0.18 | 0.984 |
