// src/commands/author-signals.ts
//
// Step 2 of docs/plans/astroturf-signals-plan.md. Two modes, both read-only against MongoDB:
//
//   --export-comments   dump comments joined to their post into
//                       data/commercial-signals/private/comments.jsonl for scripts/ner_comments.py
//   (default)           read that file plus private/ner.jsonl, canonicalize entities through
//                       AliasDictService, and write the derived CSVs:
//
//     data/commercial-signals/authors.csv    one row per hashed author (>=10 comments)
//     data/commercial-signals/mentions.csv   one row per canonical brand mention (hashed author,
//                                            anonymized brand code, subreddit, thread intent)
//     data/commercial-signals/private/brand-key.csv   brand code -> name (never committed)
//
// Author hashes use AUTHOR_HASH_SALT, which stays out of the repo. Usernames and comment text
// never leave the private/ directory.

import fs from "fs";
import path from "path";
import crypto from "crypto";
import minimist from "minimist";
import { unifiedDatabaseService as databaseService } from "../services/mongoose-database.service";
import { CommentModel } from "../models/comment.mongoose";
import { PostModel } from "../models/post.mongoose";
import { AliasDictService } from "../services/pipeline/alias-dict.service";
import { EntityLoaderService } from "../services/analysis/entity-loader.service";
import { AnalysisStorageService } from "../services/analysis/analysis-storage.service";
import { BOT_AUTHOR_PATTERN } from "./audit-corpus";
import logger from "../services/logger.service";

const OUT_DIR = path.resolve("data/commercial-signals");
const PRIV_DIR = path.join(OUT_DIR, "private");
const MIN_COMMENTS = 10;
const TAIL_SHARE = 0.05;

// Thread-level purchase intent. A question in the post title or body asking what to buy.
export const PURCHASE_QUESTION_PATTERN =
  /\b(should\s+I\s+(get|buy|pick|go\s+with)|worth\s+(it|the|buying)|recommend(ation)?s?|suggestions?|looking\s+for\s+(a|an|my|some)|which\s+(one|knife|steel|brand)\s+(should|would|do|is)|what\s+(knife|steel|brand)\s+(should|would|do)|budget\s+(of|is|around|under)|under\s+\$?\d|best\s+(knife|option|choice|bang)|help\s+me\s+(choose|decide|pick)|first\s+(knife|purchase)|gift)\b/i;

export const COMPARISON_QUESTION_PATTERN =
  /\b(vs\.?|versus|or\b.*\?|compared?\s+to|better\s+than|difference\s+between|choosing\s+between|choose\s+between|instead\s+of)\b/i;

export type ThreadIntent = "purchase" | "comparison" | "other";

export function classifyThreadIntent(title: string, content: string): ThreadIntent {
  const text = `${title}\n${content.slice(0, 1500)}`;
  if (PURCHASE_QUESTION_PATTERN.test(text)) return "purchase";
  if (COMPARISON_QUESTION_PATTERN.test(text)) return "comparison";
  return "other";
}

export interface ExportedComment {
  id: string;
  author: string;
  content: string;
  score: number;
  createdAt: string;
  subreddit: string;
  postId: string;
  postAuthor: string;
  threadIntent: ThreadIntent;
}

interface NerEntity {
  text: string;
  label: string;
  score: number;
}

interface NerRow {
  id: string;
  ents: NerEntity[];
}

export interface AuthorRow {
  author_hash: string;
  n_comments: number;
  n_brand_mentions: number;
  n_comments_with_brand: number;
  brand_mention_rate: number;
  n_distinct_brands: number;
  top_brand_share: number;
  purchase_thread_rate: number;
  purchase_thread_brand_rate: number;
  median_score: number;
  op_reply_rate: number;
  first_seen: string;
  last_seen: string;
  n_subreddits: number;
  excluded_reason: string;
}

export interface MentionRow {
  author_hash: string;
  brand_code: string;
  subreddit: string;
  thread_intent: ThreadIntent;
  match_via: "brand" | "model";
  ner_score: number;
  comment_score: number;
  month: string;
  author_bucket: "10plus" | "under10";
}

function hashAuthor(author: string, salt: string): string {
  return crypto.createHash("sha256").update(`${salt}:${author.toLowerCase()}`).digest("hex").slice(0, 16);
}

function median(xs: number[]): number {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

function toCsv<T extends object>(rows: T[]): string {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]) as (keyof T)[];
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n") + "\n";
}

function readJsonl<T>(file: string): T[] {
  return fs
    .readFileSync(file, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((l) => JSON.parse(l) as T);
}

async function exportComments(): Promise<void> {
  await databaseService.connect();
  const posts = await PostModel.find({}, { redditId: 1, title: 1, content: 1, author: 1, subreddit: 1 }).lean();
  const postById = new Map(posts.map((p) => [p.redditId, p]));
  const comments = await CommentModel.find(
    {},
    { redditId: 1, postId: 1, author: 1, content: 1, score: 1, createdAt: 1 }
  ).lean();

  fs.mkdirSync(PRIV_DIR, { recursive: true });
  const outPath = path.join(PRIV_DIR, "comments.jsonl");
  const out = fs.createWriteStream(outPath);
  let written = 0;
  for (const c of comments) {
    const p = postById.get(c.postId);
    if (!p) continue;
    const row: ExportedComment = {
      id: c.redditId,
      author: c.author,
      content: c.content,
      score: c.score,
      createdAt: new Date(c.createdAt).toISOString(),
      subreddit: p.subreddit,
      postId: p.redditId,
      postAuthor: p.author,
      threadIntent: classifyThreadIntent(p.title || "", p.content || ""),
    };
    out.write(JSON.stringify(row) + "\n");
    written++;
  }
  await new Promise<void>((resolve) => out.end(resolve));
  logger.info(`Exported ${written} comments to ${outPath}`);
  await databaseService.disconnect();
}

export interface Canonicalizer {
  brandFor(text: string, label: string): { brand: string; via: "brand" | "model" } | null;
}

export function buildCanonicalizer(dict: AliasDictService): Canonicalizer {
  return {
    brandFor(text, label) {
      if (label === "knife brand") {
        const r = dict.lookupByType(text, "brand");
        if (r.type === "exact" && r.canonicalName) return { brand: r.canonicalName, via: "brand" };
        return null;
      }
      if (label === "knife model") {
        const r = dict.lookupByType(text, "model");
        if (r.type === "exact" && r.brand) return { brand: r.brand, via: "model" };
        return null;
      }
      return null;
    },
  };
}

export function computeSignals(
  comments: ExportedComment[],
  ner: NerRow[],
  canon: Canonicalizer,
  salt: string,
  excludedAuthors: Set<string>
): {
  authors: AuthorRow[];
  mentions: MentionRow[];
  brandKey: { brand_code: string; brand: string; n: number }[];
  authorKey: { author_hash: string; author: string }[];
  summary: Record<string, number>;
} {
  const nerById = new Map(ner.map((r) => [r.id, r.ents]));
  const byAuthor = new Map<string, ExportedComment[]>();
  let bots = 0;
  for (const c of comments) {
    if (BOT_AUTHOR_PATTERN.test(c.author)) {
      bots++;
      continue;
    }
    (byAuthor.get(c.author) ?? byAuthor.set(c.author, []).get(c.author)!).push(c);
  }

  // Brand codes are assigned by descending total mention count so the key is stable across runs.
  const brandTotals = new Map<string, number>();
  const commentBrands = new Map<string, { brand: string; via: "brand" | "model"; score: number }[]>();
  for (const c of comments) {
    const ents = nerById.get(c.id);
    if (!ents || BOT_AUTHOR_PATTERN.test(c.author)) continue;
    const seen = new Map<string, { brand: string; via: "brand" | "model"; score: number }>();
    for (const e of ents) {
      const hit = canon.brandFor(e.text, e.label);
      if (!hit) continue;
      const prev = seen.get(hit.brand);
      if (!prev || prev.score < e.score) seen.set(hit.brand, { ...hit, score: e.score });
    }
    if (seen.size) {
      commentBrands.set(c.id, [...seen.values()]);
      for (const b of seen.keys()) brandTotals.set(b, (brandTotals.get(b) || 0) + 1);
    }
  }
  const brandKey = [...brandTotals.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([brand, n], i) => ({ brand_code: `B${String(i + 1).padStart(3, "0")}`, brand, n }));
  const codeOf = new Map(brandKey.map((k) => [k.brand, k.brand_code]));

  const authors: AuthorRow[] = [];
  const mentions: MentionRow[] = [];
  const authorKey: { author_hash: string; author: string }[] = [];
  let nerCovered = 0;
  for (const c of comments) if (nerById.has(c.id)) nerCovered++;

  for (const [author, cs] of byAuthor) {
    const hash = hashAuthor(author, salt);
    if (cs.length >= MIN_COMMENTS) authorKey.push({ author_hash: hash, author });
    const bucket: MentionRow["author_bucket"] = cs.length >= MIN_COMMENTS ? "10plus" : "under10";
    const perBrand = new Map<string, number>();
    let nMentions = 0;
    let nWithBrand = 0;
    let nPurchase = 0;
    let nPurchaseBrand = 0;
    let nOpReply = 0;
    const subs = new Set<string>();
    for (const c of cs) {
      subs.add(c.subreddit);
      if (c.threadIntent === "purchase") nPurchase++;
      if (c.author === c.postAuthor) nOpReply++;
      const brands = commentBrands.get(c.id);
      if (!brands) continue;
      nWithBrand++;
      if (c.threadIntent === "purchase") nPurchaseBrand++;
      for (const b of brands) {
        nMentions++;
        perBrand.set(b.brand, (perBrand.get(b.brand) || 0) + 1);
        mentions.push({
          author_hash: hash,
          brand_code: codeOf.get(b.brand)!,
          subreddit: c.subreddit,
          thread_intent: c.threadIntent,
          match_via: b.via,
          ner_score: b.score,
          comment_score: c.score,
          month: c.createdAt.slice(0, 7),
          author_bucket: bucket,
        });
      }
    }
    if (bucket !== "10plus") continue;
    const dates = cs.map((c) => c.createdAt).sort();
    authors.push({
      author_hash: hash,
      n_comments: cs.length,
      n_brand_mentions: nMentions,
      n_comments_with_brand: nWithBrand,
      brand_mention_rate: nWithBrand / cs.length,
      n_distinct_brands: perBrand.size,
      top_brand_share: nMentions ? Math.max(...perBrand.values()) / nMentions : 0,
      purchase_thread_rate: nPurchase / cs.length,
      purchase_thread_brand_rate: nWithBrand ? nPurchaseBrand / nWithBrand : 0,
      median_score: median(cs.map((c) => c.score)),
      op_reply_rate: nOpReply / cs.length,
      first_seen: dates[0].slice(0, 10),
      last_seen: dates[dates.length - 1].slice(0, 10),
      n_subreddits: subs.size,
      excluded_reason: excludedAuthors.has(author.toLowerCase()) ? "owner_account" : "",
    });
  }

  authors.sort((a, b) => b.n_comments - a.n_comments);
  return {
    authors,
    mentions,
    brandKey,
    authorKey,
    summary: {
      comments: comments.length,
      botOrDeletedComments: bots,
      nerCoveredComments: nerCovered,
      commentsWithCanonicalBrand: commentBrands.size,
      brandMentions: mentions.length,
      distinctBrands: brandKey.length,
      authorsTotal: byAuthor.size,
      authorsWith10Plus: authors.length,
      tailSize: Math.max(1, Math.round(authors.length * TAIL_SHARE)),
    },
  };
}

async function runMetrics(): Promise<void> {
  const salt = process.env.AUTHOR_HASH_SALT;
  if (!salt) throw new Error("AUTHOR_HASH_SALT is required (keep it out of the repo)");
  const excluded = new Set(
    (process.env.SIGNALS_EXCLUDED_AUTHORS || "")
      .split(",")
      .map((s) => s.trim().toLowerCase())
      .filter(Boolean)
  );

  const comments = readJsonl<ExportedComment>(path.join(PRIV_DIR, "comments.jsonl"));
  const ner = readJsonl<NerRow>(path.join(PRIV_DIR, "ner.jsonl"));

  await databaseService.connect();
  const entities = await new EntityLoaderService(new AnalysisStorageService()).loadAllEntities();
  await databaseService.disconnect();
  const dict = new AliasDictService();
  dict.build(entities);

  const result = computeSignals(comments, ner, buildCanonicalizer(dict), salt, excluded);

  fs.mkdirSync(PRIV_DIR, { recursive: true });
  fs.writeFileSync(path.join(OUT_DIR, "authors.csv"), toCsv(result.authors));
  fs.writeFileSync(path.join(OUT_DIR, "mentions.csv"), toCsv(result.mentions));
  fs.writeFileSync(path.join(PRIV_DIR, "brand-key.csv"), toCsv(result.brandKey));
  fs.writeFileSync(path.join(PRIV_DIR, "author-key.csv"), toCsv(result.authorKey));
  fs.writeFileSync(
    path.join(OUT_DIR, "signals-summary.json"),
    JSON.stringify({ generatedAt: new Date().toISOString(), ...result.summary }, null, 2)
  );
  console.log(JSON.stringify(result.summary, null, 2));
  logger.info(`Wrote authors.csv (${result.authors.length}) and mentions.csv (${result.mentions.length}) to ${OUT_DIR}`);
}

if (require.main === module) {
  const args = minimist(process.argv.slice(2));
  (args["export-comments"] ? exportComments() : runMetrics()).catch((error) => {
    logger.error("author-signals failed", { error });
    process.exit(1);
  });
}
