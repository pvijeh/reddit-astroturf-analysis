# Commercial-posting signals: derived data

Files in this folder are the outputs of the study described in the top-level README. Nothing here
contains a username or a comment. The `private/` folder (raw comments, NER output, the brand
code key) is gitignored.

## How the files are made

```bash
MONGODB_URI=... MONGODB_DB_NAME=knifeRedditData REDDIT_*=... npm run signals:refresh -- --subs knives,knifeclub --min-age-hours 48
MONGODB_URI=... MONGODB_DB_NAME=knifeRedditData npm run signals:audit      # audit.json
MONGODB_URI=... MONGODB_DB_NAME=knifeRedditData npm run signals:export     # private/comments.jsonl
~/ner-venv/bin/python scripts/ner_comments.py                              # private/ner.jsonl (~35 min on 8 CPU cores)
AUTHOR_HASH_SALT=<random> MONGODB_URI=... MONGODB_DB_NAME=knifeRedditData npm run signals:metrics
~/ner-venv/bin/python scripts/signals_baseline.py                          # results.json, results.md, charts/
```

`signals:refresh` refetches the comment tree of every stored post in the given subreddits
that is older than `--min-age-hours` and has no `commentsRefreshedAt` yet, upserting comments by
`redditId`. Run it before the audit when posts were scraped while new; it took 10 hours for
3,607 posts. `--dry-run` prints the count, `--limit N` caps it.

`AUTHOR_HASH_SALT` is not stored anywhere in the repo. It is generated per run, so
`author_hash` values do not match across runs, and `brand_code` is reassigned by mention count
per run. `SIGNALS_EXCLUDED_AUTHORS` is a
comma-separated list of Peter's own accounts; they stay in authors.csv with
`excluded_reason=owner_account` and are left out of the tail and the baseline.

## Files

- `audit.json`: comment and post counts per subreddit and month, author counts, how many
  scraped comments the old `multipassentitymentions` rows cover.
- `authors.csv`: one row per author with 10 or more comments. `author_hash` is the first 16 hex
  chars of sha256(salt:username).
- `mentions.csv`: one row per (comment, brand) pair where GLiNER found a brand or model and the
  alias dictionary resolved it to a brand in the New Knife Day catalog. `brand_code` is B001,
  B002, ... in order of total mention count.
- `results.json`, `results.md`: the tail definition, observed shares, shuffled baseline and
  bootstrap intervals.
- `charts/`: the three charts results.md refers to, plus `account-histories.png`.
- `account-summary.json`, `account-summary.md`: medians and Mann-Whitney p-values comparing the
  full Reddit histories of 23 tail accounts (the ones behind B001, B003, B004) with 23 controls
  drawn at random from the tail's corpus comment-count range (10 to 102). Controls are not paired
  one-to-one; their median corpus comment count is 23 against 13 for the tail. Delete
  `private/histories.jsonl` before rerunning after a reselection or salt change, because the fetch
  resumes by username and keeps the old group and hash. Made by:

```bash
~/ner-venv/bin/python scripts/select_accounts.py          # private/accounts.csv
MONGODB_URI=... REDDIT_*=... npm run signals:histories     # private/histories.jsonl, up to 1,000 comments and posts each
~/ner-venv/bin/python scripts/account_features.py         # account-summary.*, charts/account-histories.png
```

  The per-account feature rows stay in `private/` because 46 hashed rows with account age and
  karma are enough to re-identify someone who has the same corpus.

## What the numbers do not say

The NER pass uses the base `urchade/gliner_multi-v2.1` model, not the fine-tuned knife model,
because the fine-tuned weights are not published. Brand recall is therefore lower than in the
live pipeline, and the 100-comment hand-label check in the plan has not been done yet. Until it
is, the shares in results.md describe this corpus and this model, not Reddit.
