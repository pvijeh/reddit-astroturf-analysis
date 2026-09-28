# reddit-astroturf-analysis

Code and anonymized data behind [Does Reddit have an astroturfing problem? What the data suggests](https://www.petervijeh.com/projects/reddit-astroturf).

The question: in the "what should I buy" threads of six knife subreddits, do a few brand-heavy accounts write more of the brand recommendations than chance would give them? And if they do, do their full Reddit histories look like prepared paid accounts or like ordinary users?

## Recompute the headline numbers

You need Python 3.12.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/signals_baseline.py
git diff --stat data/commercial-signals/
```

`signals_baseline.py` reads `authors.csv` and `mentions.csv` and rewrites `results.json`, `results.md` and the charts in `data/commercial-signals/`. With the default seed it reproduces the committed `results.json` and `results.md` exactly, so `git diff` shows no change to either. Those two files hold the 11.3% against 7.9% tail share, the per-subreddit and per-brand tables, and the p-values quoted in the article. The PNG charts may differ by a few bytes between matplotlib versions.

The account-history comparison (`account-summary.json`, 4.5-year median account age and the rest) cannot be recomputed from this repo. Its inputs are the 46 accounts' usernames and histories, which are not published (see below).

## What is here

- `data/commercial-signals/authors.csv`: one row per author with 10 or more comments in the corpus. `author_hash` is the first 16 hex characters of sha256(salt:username), with a salt that was generated for the run and not kept.
- `data/commercial-signals/mentions.csv`: one row per (comment, brand) pair. Brands are coded B001, B002, ... in order of total mentions. The key from code to brand name is not published.
- `data/commercial-signals/results.*`, `charts/`: output of `signals_baseline.py`.
- `data/commercial-signals/account-summary.*`: medians and Mann-Whitney p-values for 23 tail accounts against 23 comparison accounts.
- `data/commercial-signals/audit.json`: comment, post and author counts per subreddit and month.
- `data/commercial-signals/README.md`: how each file was produced, and what the numbers do not say.
- `scripts/`: the Python steps. `signals_baseline.py` runs on the published data. `ner_comments.py`, `select_accounts.py` and `account_features.py` need the private files and are here so you can read exactly what they do.
- `collection/`: the TypeScript commands that pulled comments from MongoDB, hashed authors and fetched account histories. They are copied from the private New Knife Day scraper and import its database and Reddit services, so they will not run on their own. They are included to show the thread-intent regex, the bot filter and the hashing.

## What is not here, and why

Comment text, usernames, comment IDs, account histories and the brand-code key. Reddit's Data API terms do not allow republishing content pulled through the API, and the article names no account and no brand. The 46 per-account history rows stay private because account age and karma are enough to re-identify someone who has the same corpus.

The brand tags come from the stock `urchade/gliner_multi-v2.1` model, not a knife-tuned one, and neither the brand tags nor the buying-thread regex have been checked against hand labels yet. Every percentage here is a percentage of machine labels.
