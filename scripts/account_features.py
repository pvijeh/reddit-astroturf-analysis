"""Turn private account histories into hashed per-account features and a tail-vs-control table.

Reads  data/commercial-signals/private/histories.jsonl   (from npm run signals:histories)
       data/commercial-signals/private/accounts.csv      (from scripts/select_accounts.py)
       data/commercial-signals/private/brand-key.csv
Writes data/commercial-signals/private/account-features.csv  one hashed row per account (kept private: 46 rows re-identify)
       data/commercial-signals/account-summary.json     medians per group plus Mann-Whitney p-values
       data/commercial-signals/account-summary.md
       data/commercial-signals/charts/account-*.png

Features per account (all from the account's own public history, up to ~1,000 comments and posts):
  account_age_days, n_comments_total, n_submissions_total, link_karma, comment_karma,
  share_comments_knife_subs, n_subreddits, top_sub_share,
  days_creation_to_first_knife_comment, share_history_before_first_knife,
  share_comments_naming_focal_brand (tail only), share_comments_naming_any_knife_brand,
  n_distinct_knife_brands_named, share_knife_comments_in_purchase_threads,
  share_comments_with_store_link, share_comments_with_any_link,
  comments_per_active_day, share_comments_in_top3_hours, median_comment_len,
  share_comments_scored_le1, history_covers_full (True if we got everything the API returns).

    ~/ner-venv/bin/python scripts/account_features.py
"""

import json
import os
import re
from collections import Counter, defaultdict

import matplotlib
import numpy as np
import pandas as pd
from scipy.stats import mannwhitneyu

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "commercial-signals")
PRIV = os.path.join(OUT, "private")
CHARTS = os.path.join(OUT, "charts")

# Reddit listings stop near 1,000 items per endpoint; the fetch returned up to 1,993 comments
# per account, so anything at or above this count is treated as truncated.
HISTORY_CAP = 1900

KNIFE_SUBS = {s.lower() for s in ["knives", "knifeclub", "KnifeSteels", "chefknives", "japaneseknives", "FixedBladeEdc"]}
KNIFE_ADJACENT = KNIFE_SUBS | {
    s.lower()
    for s in ["EDC", "knife_swap", "Knife_Swap", "balisong", "Bladesmith", "knifemaking", "sharpening", "TrueChefKnives",
              "KitchenConfidential", "Cooking", "chefknifeswap", "Multitools", "Leatherman", "spyderco", "Benchmade",
              "civivi", "kershaw", "Bushcraft", "camping", "preppers"]
}
PURCHASE = re.compile(
    r"\b(should\s+I\s+(get|buy|pick|go\s+with)|worth\s+(it|the|buying)|recommend(ation)?s?|suggestions?|"
    r"looking\s+for\s+(a|an|my|some)|which\s+(one|knife|steel|brand)\s+(should|would|do|is)|"
    r"what\s+(knife|steel|brand)\s+(should|would|do)|budget\s+(of|is|around|under)|under\s+\$?\d|"
    r"best\s+(knife|option|choice|bang)|help\s+me\s+(choose|decide|pick)|first\s+(knife|purchase)|gift)\b",
    re.I,
)
URL = re.compile(r"https?://[^\s)\]]+", re.I)
STORE = re.compile(
    r"(amazon\.|amzn\.|bladehq|knifecenter|knivesshipfree|dlttrading|smkw\.|chefknivestogo|knifewear|"
    r"cutleryandmore|shop\.|store\.|/products?/|ref=|affiliate|aff=|tag=|utm_)",
    re.I,
)


def brand_patterns(brands: pd.DataFrame) -> dict[str, re.Pattern]:
    pats = {}
    for _, r in brands.iterrows():
        name = str(r.brand).strip()
        if len(name) < 3:
            continue
        pats[r.brand_code] = re.compile(r"\b" + re.escape(name) + r"\b", re.I)
    return pats


def features(rec: dict, focal_pat: re.Pattern | None, all_pats: dict[str, re.Pattern], corpus_ids: set[str]) -> dict:
    cs = pd.DataFrame(rec["comments"])
    subs = pd.DataFrame(rec["submissions"])
    created = pd.Timestamp(rec["createdAt"])
    fetched = pd.Timestamp(rec["fetchedAt"])
    # A --per-user limit below the listing ceiling also truncates the history; rows written
    # before the limit was recorded used the default 1000, which the ceiling already covers.
    cap = min(HISTORY_CAP, rec["limit"]) if "limit" in rec else HISTORY_CAP
    covers_full = len(cs) < cap
    row: dict = {
        "author_hash": rec["author_hash"],
        "group": rec["group"],
        "account_age_days": (fetched - created).days,
        "link_karma": rec["linkKarma"],
        "comment_karma": rec["commentKarma"],
        "n_comments_total": len(cs),
        "n_submissions_total": len(subs),
        "history_covers_full": covers_full,
        "n_corpus_comments": len(corpus_ids),
        "share_corpus_comments_visible": (
            len(corpus_ids & set(cs.id)) / len(corpus_ids) if len(corpus_ids) and len(cs) else (0.0 if len(corpus_ids) else np.nan)
        ),
    }
    if len(cs) == 0:
        return row
    cs["createdAt"] = pd.to_datetime(cs.createdAt)
    cs["sub"] = cs.subreddit.str.lower()
    cs["knife"] = cs["sub"].isin(KNIFE_SUBS)
    cs["knife_adj"] = cs["sub"].isin(KNIFE_ADJACENT)
    # Only meaningful when the fetch reached the account's first comment; a capped
    # history hides older knife activity, so these two fields stay NaN there.
    first_knife = cs.loc[cs.knife, "createdAt"].min() if covers_full else pd.NaT
    row.update(
        {
            "history_first_comment_days_ago": (fetched - cs.createdAt.min()).days,
            "share_comments_knife_subs": cs.knife.mean(),
            "share_comments_knife_adjacent": cs.knife_adj.mean(),
            "n_subreddits": cs["sub"].nunique(),
            "top_sub_share": cs["sub"].value_counts(normalize=True).iloc[0],
            "days_creation_to_first_knife_comment": (first_knife - created).days if pd.notna(first_knife) else np.nan,
            "share_history_before_first_knife": (cs.createdAt < first_knife).mean() if pd.notna(first_knife) else np.nan,
            "share_comments_naming_focal_brand": cs.body.apply(lambda b: bool(focal_pat.search(b))).mean() if focal_pat else np.nan,
            "share_knife_comments_naming_focal_brand": (
                cs.loc[cs.knife, "body"].apply(lambda b: bool(focal_pat.search(b))).mean() if focal_pat and cs.knife.any() else np.nan
            ),
            "share_comments_naming_any_knife_brand": cs.body.apply(lambda b: any(p.search(b) for p in all_pats.values())).mean(),
            "n_distinct_knife_brands_named": len({k for k, p in all_pats.items() if cs.body.apply(lambda b: bool(p.search(b))).any()}),
            "share_knife_comments_in_purchase_threads": (
                cs.loc[cs.knife, "linkTitle"].apply(lambda t: bool(PURCHASE.search(t))).mean() if cs.knife.any() else np.nan
            ),
            "share_comments_with_any_link": cs.body.apply(lambda b: bool(URL.search(b))).mean(),
            "share_comments_with_store_link": cs.body.apply(lambda b: any(STORE.search(u) for u in URL.findall(b))).mean(),
            "comments_per_active_day": len(cs) / max(1, cs.createdAt.dt.date.nunique()),
            "share_comments_in_top3_hours": sum(Counter(cs.createdAt.dt.hour).most_common(3)[i][1] for i in range(min(3, cs.createdAt.dt.hour.nunique()))) / len(cs),
            "median_comment_len": cs.body.str.len().median(),
            "share_comments_scored_le1": (cs.score <= 1).mean(),
            "share_comments_as_op": cs.isSubmitter.mean(),
        }
    )
    return row


def main() -> None:
    accounts = pd.read_csv(os.path.join(PRIV, "accounts.csv")).fillna({"focal_brand_code": ""})
    brands = pd.read_csv(os.path.join(PRIV, "brand-key.csv"))
    pats = brand_patterns(brands[brands.n >= 20])
    focal = dict(zip(accounts.author_hash, accounts.focal_brand_code))

    corpus_by_author: dict[str, set[str]] = defaultdict(set)
    for line in open(os.path.join(PRIV, "comments.jsonl")):
        c = json.loads(line)
        corpus_by_author[c["author"]].add(c["id"])

    rows = []
    for line in open(os.path.join(PRIV, "histories.jsonl")):
        rec = json.loads(line)
        if rec.get("unavailable"):
            rows.append({"author_hash": rec["author_hash"], "group": rec["group"], "unavailable": True})
            continue
        code = focal.get(rec["author_hash"], "")
        rows.append(features(rec, pats.get(code), pats, corpus_by_author.get(rec["username"], set())))
    df = pd.DataFrame(rows)
    if "unavailable" not in df:
        df["unavailable"] = False
    df["unavailable"] = df.unavailable.fillna(False).astype(bool)
    df["n_comments_total"] = df.n_comments_total.fillna(0)
    df["focal_brand_code"] = df.author_hash.map(focal)
    df["profile_history_hidden"] = (df.n_comments_total == 0) & (df.comment_karma > 100)
    df.to_csv(os.path.join(PRIV, "account-features.csv"), index=False)

    usable = df[~df.unavailable & (df.n_comments_total > 0)]
    num_cols = [c for c in usable.columns if usable[c].dtype.kind in "fi"]
    summary = {"n_tail": int((df.group == "tail").sum()), "n_control": int((df.group == "control").sum()),
               "n_tail_usable": int((usable.group == "tail").sum()), "n_control_usable": int((usable.group == "control").sum()),
               "n_tail_hidden_or_unavailable": int(((df.group == "tail") & ~df.author_hash.isin(usable.author_hash)).sum()),
               "n_control_hidden_or_unavailable": int(((df.group == "control") & ~df.author_hash.isin(usable.author_hash)).sum()),
               "features": {}}
    md = ["# Account histories: tail vs control", "",
          f"Tail {summary['n_tail']} accounts ({summary['n_tail_usable']} with readable history), control {summary['n_control']} ({summary['n_control_usable']}).",
          f"Hidden or unavailable histories: tail {summary['n_tail_hidden_or_unavailable']}, control {summary['n_control_hidden_or_unavailable']}.", "",
          "| feature | tail median | control median | tail IQR | control IQR | p (Mann-Whitney) |", "|---|---|---|---|---|---|"]
    for c in num_cols:
        t = usable.loc[usable.group == "tail", c].dropna()
        k = usable.loc[usable.group == "control", c].dropna()
        if len(t) < 3 or len(k) < 3:
            continue
        p = mannwhitneyu(t, k, alternative="two-sided").pvalue
        summary["features"][c] = {"tail_median": float(t.median()), "control_median": float(k.median()),
                                  "tail_q1": float(t.quantile(.25)), "tail_q3": float(t.quantile(.75)),
                                  "control_q1": float(k.quantile(.25)), "control_q3": float(k.quantile(.75)),
                                  "n_tail": int(len(t)), "n_control": int(len(k)), "p": float(p)}
        md.append(f"| {c} | {t.median():.3g} | {k.median():.3g} | {t.quantile(.25):.3g}-{t.quantile(.75):.3g} | {k.quantile(.25):.3g}-{k.quantile(.75):.3g} | {p:.3f} |")
    json.dump(summary, open(os.path.join(OUT, "account-summary.json"), "w"), indent=2)
    open(os.path.join(OUT, "account-summary.md"), "w").write("\n".join(md) + "\n")

    os.makedirs(CHARTS, exist_ok=True)
    plot = [("account_age_days", "Account age (days)"), ("share_comments_knife_subs", "Share of comments in the 6 knife subs"),
            ("share_comments_naming_any_knife_brand", "Share of comments naming a knife brand"),
            ("n_subreddits", "Distinct subreddits commented in"), ("share_comments_with_store_link", "Share of comments with a store link"),
            ("days_creation_to_first_knife_comment", "Days from account creation to first knife-sub comment")]
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for ax, (c, title) in zip(axes.flat, plot):
        data = [usable.loc[usable.group == g, c].dropna() for g in ("tail", "control")]
        ax.boxplot(data, tick_labels=["tail", "control"], showfliers=True)
        for i, d in enumerate(data):
            ax.scatter(np.random.normal(i + 1, 0.05, len(d)), d, s=12, alpha=.6)
        ax.set_title(title, fontsize=10)
    fig.suptitle("Full Reddit histories of brand-heavy tail accounts vs matched controls (hashed accounts, no text)")
    fig.tight_layout()
    fig.savefig(os.path.join(CHARTS, "account-histories.png"), dpi=130)
    print("\n".join(md))


if __name__ == "__main__":
    main()
