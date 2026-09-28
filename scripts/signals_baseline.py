"""Step 3 of docs/plans/astroturf-signals-plan.md: tail definition, shuffled baseline, bootstrap
intervals and charts over the CSVs written by `npm run signals:metrics`.

Reads  data/commercial-signals/authors.csv, mentions.csv
Writes data/commercial-signals/results.json, results.md, charts/*.png

No usernames or comment text are read here; the inputs are already hashed and anonymized.

    ~/ner-venv/bin/python scripts/signals_baseline.py [--shuffles 1000] [--boot 1000] [--seed 1]
"""
import argparse
import json
import os

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT = os.path.join(ROOT, "data", "commercial-signals")
CHARTS = os.path.join(OUT, "charts")
TAIL_SHARE = 0.05
MIN_BRAND_MENTIONS = 20
MIN_TAIL_MENTIONS = 3


def rank_tail(authors: pd.DataFrame) -> set[str]:
    """Composite rank: mean of ranks on brand_mention_rate, top_brand_share,
    purchase_thread_brand_rate. Top TAIL_SHARE by that rank is the tail.
    Authors with no brand mention at all are never in the tail."""
    a = authors[(authors.excluded_reason == "") & (authors.n_brand_mentions > 0)].copy()
    cols = ["brand_mention_rate", "top_brand_share", "purchase_thread_brand_rate"]
    score = sum(a[c].rank(pct=True) for c in cols) / len(cols)
    k = max(1, round(len(authors[authors.excluded_reason == ""]) * TAIL_SHARE))
    return set(a.assign(score=score).nlargest(k, "score").author_hash)


def tail_share(mentions: pd.DataFrame, tail: set[str], by: str | None) -> pd.Series | float:
    m = mentions[mentions.thread_intent == "purchase"]
    is_tail = m.author_hash.isin(tail)
    if by is None:
        return float(is_tail.mean()) if len(m) else float("nan")
    return is_tail.groupby(m[by]).mean()


def author_metrics_from_mentions(authors: pd.DataFrame, mentions: pd.DataFrame) -> pd.DataFrame:
    """Recompute the mention-derived author columns after a brand shuffle. brand_mention_rate is
    unchanged by construction (comment counts and mention counts per author are preserved)."""
    g = mentions.groupby("author_hash")
    top = g.brand_code.agg(lambda s: s.value_counts().iloc[0] / len(s))
    out = authors.set_index("author_hash").copy()
    out["top_brand_share"] = top.reindex(out.index).fillna(0).values
    return out.reset_index()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shuffles", type=int, default=1000)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    authors = pd.read_csv(os.path.join(OUT, "authors.csv"), dtype={"excluded_reason": str}).fillna(
        {"excluded_reason": ""}
    )
    mentions = pd.read_csv(os.path.join(OUT, "mentions.csv"))
    owner_hashes = set(authors[authors.excluded_reason != ""].author_hash)
    m10 = mentions[(mentions.author_bucket == "10plus") & ~mentions.author_hash.isin(owner_hashes)]
    tail = rank_tail(authors)

    observed_all = tail_share(m10, tail, None)
    observed_sub = tail_share(m10, tail, "subreddit")
    brand_counts = m10[m10.thread_intent == "purchase"].brand_code.value_counts()
    big_brands = brand_counts[brand_counts >= MIN_BRAND_MENTIONS].index
    observed_brand = tail_share(m10[m10.brand_code.isin(big_brands)], tail, "brand_code")

    # Shuffled baseline: permute brand labels across mention rows. Each author keeps the same
    # number of comments and mentions; each brand keeps its overall frequency.
    sh_all, sh_sub, sh_brand = [], [], []
    for _ in range(args.shuffles):
        shuffled = m10.assign(brand_code=rng.permutation(m10.brand_code.values))
        a2 = author_metrics_from_mentions(authors, shuffled)
        t2 = rank_tail(a2)
        sh_all.append(tail_share(shuffled, t2, None))
        sh_sub.append(tail_share(shuffled, t2, "subreddit"))
        sh_brand.append(tail_share(shuffled[shuffled.brand_code.isin(big_brands)], t2, "brand_code"))
    sh_all = np.array(sh_all)
    sh_sub = pd.DataFrame(sh_sub).reindex(columns=observed_sub.index)
    sh_brand = pd.DataFrame(sh_brand).reindex(columns=observed_brand.index)

    # Bootstrap over authors (resample authors with replacement, keep their mention rows).
    hashes = m10.author_hash.unique()
    rows_by_author = {h: g for h, g in m10.groupby("author_hash")}
    boot_all = []
    for _ in range(args.boot):
        pick = rng.choice(hashes, size=len(hashes), replace=True)
        sample = pd.concat([rows_by_author[h] for h in pick])
        boot_all.append(tail_share(sample, tail, None))
    boot_all = np.array(boot_all)

    def p_value(obs: float, dist: np.ndarray) -> float:
        return float((np.sum(dist >= obs) + 1) / (len(dist) + 1))

    per_sub = []
    for sub, obs in observed_sub.items():
        dist = sh_sub[sub].dropna().values
        n = int((m10.thread_intent == "purchase")[m10.subreddit == sub].sum())
        per_sub.append(
            dict(subreddit=sub, purchase_thread_mentions=n, observed=round(float(obs), 4),
                 shuffled_mean=round(float(dist.mean()), 4), shuffled_p95=round(float(np.quantile(dist, 0.95)), 4),
                 p_value=round(p_value(obs, dist), 4))
        )
    per_brand = []
    for b, obs in observed_brand.items():
        dist = sh_brand[b].dropna().values
        per_brand.append(
            dict(brand_code=b, purchase_thread_mentions=int(brand_counts[b]), observed=round(float(obs), 4),
                 shuffled_mean=round(float(dist.mean()), 4), shuffled_p95=round(float(np.quantile(dist, 0.95)), 4),
                 p_value=round(p_value(obs, dist), 4))
        )
    per_brand.sort(key=lambda r: -r["observed"])

    tail_rows = authors[authors.author_hash.isin(tail)]
    results = dict(
        inputs=dict(
            authors_10plus=int((authors.excluded_reason == "").sum()),
            owner_accounts_excluded=len(owner_hashes),
            tail_size=len(tail),
            brand_mentions_10plus=len(m10),
            purchase_thread_mentions_10plus=int((m10.thread_intent == "purchase").sum()),
            under10_mentions_not_used=int((mentions.author_bucket == "under10").sum()),
            shuffles=args.shuffles,
            bootstrap=args.boot,
        ),
        headline=dict(
            share_of_purchase_thread_brand_mentions_from_tail=round(observed_all, 4),
            bootstrap_ci95=[round(float(np.quantile(boot_all, 0.025)), 4), round(float(np.quantile(boot_all, 0.975)), 4)],
            shuffled_mean=round(float(sh_all.mean()), 4),
            shuffled_ci95=[round(float(np.quantile(sh_all, 0.025)), 4), round(float(np.quantile(sh_all, 0.975)), 4)],
            p_value=round(p_value(observed_all, sh_all), 4),
        ),
        tail_profile=dict(
            median_comments=float(tail_rows.n_comments.median()),
            median_brand_mention_rate=round(float(tail_rows.brand_mention_rate.median()), 3),
            median_top_brand_share=round(float(tail_rows.top_brand_share.median()), 3),
            median_distinct_brands=float(tail_rows.n_distinct_brands.median()),
            median_score=float(tail_rows.median_score.median()),
            all_10plus_median_brand_mention_rate=round(float(authors.brand_mention_rate.median()), 3),
            all_10plus_median_top_brand_share=round(float(authors.top_brand_share.median()), 3),
            all_10plus_median_score=float(authors.median_score.median()),
        ),
        per_subreddit=per_sub,
        per_brand=per_brand,
    )
    os.makedirs(CHARTS, exist_ok=True)
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, indent=2)

    # Charts
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(sh_all, bins=40, color="#bbb", label=f"{args.shuffles} shuffles")
    ax.axvline(observed_all, color="C3", label=f"observed {observed_all:.1%}")
    ax.set_xlabel("share of purchase-thread brand mentions from the top-5% tail")
    ax.set_ylabel("shuffles")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS, "tail-share-vs-shuffled.png"), dpi=130)

    fig, ax = plt.subplots(figsize=(7, 4))
    subs = [r["subreddit"] for r in per_sub]
    ax.bar(subs, [r["observed"] for r in per_sub], color="C3", label="observed")
    ax.scatter(subs, [r["shuffled_mean"] for r in per_sub], color="k", zorder=3, label="shuffled mean")
    ax.scatter(subs, [r["shuffled_p95"] for r in per_sub], color="k", marker="_", s=300, zorder=3, label="shuffled 95th pct")
    ax.set_ylabel("tail share of purchase-thread brand mentions")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS, "tail-share-by-subreddit.png"), dpi=130)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.scatter(authors.brand_mention_rate, authors.top_brand_share, s=8, color="#999", label="authors with 10+ comments")
    ax.scatter(tail_rows.brand_mention_rate, tail_rows.top_brand_share, s=14, color="C3", label="tail")
    ax.set_xlabel("share of an author's comments that name a brand")
    ax.set_ylabel("share of the author's brand mentions that are one brand")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS, "authors-scatter.png"), dpi=130)

    md = [
        "# Commercial-posting signals: results",
        "",
        f"Generated from authors.csv / mentions.csv. {results['inputs']['authors_10plus']} authors with 10+ comments; "
        f"tail = top {len(tail)} by composite rank; {results['inputs']['purchase_thread_mentions_10plus']} brand mentions in purchase threads.",
        "",
        f"Share of purchase-thread brand mentions from the tail: **{observed_all:.1%}** "
        f"(bootstrap 95% {results['headline']['bootstrap_ci95'][0]:.1%} to {results['headline']['bootstrap_ci95'][1]:.1%}). "
        f"Shuffled baseline mean {results['headline']['shuffled_mean']:.1%} "
        f"(95% {results['headline']['shuffled_ci95'][0]:.1%} to {results['headline']['shuffled_ci95'][1]:.1%}), p = {results['headline']['p_value']}.",
        "",
        "## By subreddit",
        "",
        "| subreddit | purchase-thread mentions | observed | shuffled mean | shuffled 95th | p |",
        "|---|---|---|---|---|---|",
    ]
    for r in per_sub:
        md.append(f"| {r['subreddit']} | {r['purchase_thread_mentions']} | {r['observed']:.1%} | {r['shuffled_mean']:.1%} | {r['shuffled_p95']:.1%} | {r['p_value']} |")
    md += ["", f"## By brand (anonymized, >= {MIN_BRAND_MENTIONS} purchase-thread mentions)", "",
           "| brand | purchase-thread mentions | observed | shuffled mean | shuffled 95th | p |", "|---|---|---|---|---|---|"]
    for r in per_brand:
        md.append(f"| {r['brand_code']} | {r['purchase_thread_mentions']} | {r['observed']:.1%} | {r['shuffled_mean']:.1%} | {r['shuffled_p95']:.1%} | {r['p_value']} |")
    md += ["", "## Tail profile (medians)", "", "| | tail | all 10+ authors |", "|---|---|---|",
           f"| comments | {results['tail_profile']['median_comments']} | {float(authors.n_comments.median())} |",
           f"| brand mention rate | {results['tail_profile']['median_brand_mention_rate']} | {results['tail_profile']['all_10plus_median_brand_mention_rate']} |",
           f"| top-brand share | {results['tail_profile']['median_top_brand_share']} | {results['tail_profile']['all_10plus_median_top_brand_share']} |",
           f"| comment score | {results['tail_profile']['median_score']} | {results['tail_profile']['all_10plus_median_score']} |",
           ""]
    with open(os.path.join(OUT, "results.md"), "w") as f:
        f.write("\n".join(md))
    print(json.dumps(results["headline"], indent=2))
    print(json.dumps(results["per_subreddit"], indent=2))


if __name__ == "__main__":
    main()
