"""Pick the accounts whose full Reddit histories get pulled (docs/plans/astroturf-signals-plan.md,
"article 2" step).

Tail group: tail authors (same rank_tail as signals_baseline.py) with at least one
purchase-thread mention of a focal brand. Control group: the same number of non-tail
authors, drawn at random from authors with a comment count in the tail's range and at least
one purchase-thread brand mention.

Reads  data/commercial-signals/{authors,mentions}.csv and private/{author-key,brand-key}.csv
Writes data/commercial-signals/private/accounts.csv  (username, author_hash, group, focal_brand_code)

    ~/ner-venv/bin/python scripts/select_accounts.py [--brands B001,B003,B004] [--seed 1]
"""

import argparse
import os

import numpy as np
import pandas as pd

from signals_baseline import OUT, rank_tail

PRIV = os.path.join(OUT, "private")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brands", default="B001,B003,B004")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    focal = args.brands.split(",")
    rng = np.random.default_rng(args.seed)

    authors = pd.read_csv(os.path.join(OUT, "authors.csv"), dtype={"excluded_reason": str}).fillna(
        {"excluded_reason": ""}
    )
    mentions = pd.read_csv(os.path.join(OUT, "mentions.csv"))
    key = pd.read_csv(os.path.join(PRIV, "author-key.csv"))

    tail = rank_tail(authors)
    pm = mentions[(mentions.thread_intent == "purchase") & (mentions.author_bucket == "10plus")]

    focal_pm = pm[pm.brand_code.isin(focal) & pm.author_hash.isin(tail)]
    tail_focal = (
        focal_pm.groupby("author_hash").brand_code.agg(lambda s: s.value_counts().index[0]).rename("focal_brand_code")
    )
    tail_rows = authors[authors.author_hash.isin(tail_focal.index)].merge(tail_focal, on="author_hash")
    tail_rows["group"] = "tail"

    lo, hi = tail_rows.n_comments.min(), tail_rows.n_comments.max()
    pool = authors[
        (authors.excluded_reason == "")
        & ~authors.author_hash.isin(tail)
        & authors.n_comments.between(lo, hi)
        & authors.author_hash.isin(pm.author_hash)
    ]
    ctrl_idx = rng.choice(pool.index, size=min(len(tail_rows), len(pool)), replace=False)
    ctrl_rows = pool.loc[ctrl_idx].copy()
    ctrl_rows["group"] = "control"
    ctrl_rows["focal_brand_code"] = ""

    out = pd.concat([tail_rows, ctrl_rows])[["author_hash", "group", "focal_brand_code", "n_comments"]]
    out = out.merge(key, on="author_hash", how="left")
    out.to_csv(os.path.join(PRIV, "accounts.csv"), index=False)
    print(out.groupby(["group", "focal_brand_code"]).size())
    print(f"comment range {lo}-{hi}; control pool {len(pool)}")


if __name__ == "__main__":
    main()
