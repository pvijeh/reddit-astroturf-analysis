// src/commands/audit-corpus.ts
//
// Read-only audit of the comment corpus for the commercial-posting-signals study
// (docs/plans/astroturf-signals-plan.md, step 1). Writes one JSON file and never
// writes to MongoDB.
//
//   MONGODB_URI=... MONGODB_DB_NAME=knifeRedditData npm run signals:audit -- --out data/commercial-signals/audit.json

import fs from "fs";
import path from "path";
import minimist from "minimist";
import { unifiedDatabaseService as databaseService } from "../services/mongoose-database.service";
import { CommentModel } from "../models/comment.mongoose";
import { PostModel } from "../models/post.mongoose";
import { MultipassEntityMention } from "../models/multipass/multipass-entity-mention.model";
import logger from "../services/logger.service";

export const BOT_AUTHOR_PATTERN = /^(\[deleted\]|AutoModerator|RemindMeBot|.*bot)$/i;

interface CountRow {
  _id: string;
  n: number;
}

async function main() {
  const args = minimist(process.argv.slice(2));
  const outPath = path.resolve(args.out || "data/commercial-signals/audit.json");

  await databaseService.connect();

  const totalComments = await CommentModel.countDocuments();
  const totalPosts = await PostModel.countDocuments();

  const postsBySub = (await PostModel.aggregate<CountRow>([
    { $group: { _id: "$subreddit", n: { $sum: 1 } } },
    { $sort: { n: -1 } },
  ])).map((r) => [r._id, r.n]);

  // Comments carry no subreddit; join through posts once and reuse.
  const joined = await CommentModel.aggregate<{
    _id: string;
    author: string;
    month: string;
    sub: string;
  }>([
    { $lookup: { from: "posts", localField: "postId", foreignField: "redditId", as: "p" } },
    { $unwind: "$p" },
    {
      $project: {
        _id: "$redditId",
        author: 1,
        sub: "$p.subreddit",
        month: { $substr: [{ $dateToString: { date: "$createdAt", format: "%Y-%m" } }, 0, 7] },
      },
    },
  ]);

  const mentionCommentIds = new Set<string>(
    (await MultipassEntityMention.distinct("commentId")).filter(Boolean) as string[]
  );

  const bySub: Record<string, { comments: number; withMentionRows: number }> = {};
  const byMonth: Record<string, number> = {};
  const perAuthor = new Map<string, number>();
  let botOrDeleted = 0;
  for (const c of joined) {
    const s = (bySub[c.sub] ??= { comments: 0, withMentionRows: 0 });
    s.comments++;
    if (mentionCommentIds.has(c._id)) s.withMentionRows++;
    byMonth[c.month] = (byMonth[c.month] || 0) + 1;
    if (BOT_AUTHOR_PATTERN.test(c.author)) botOrDeleted++;
    else perAuthor.set(c.author, (perAuthor.get(c.author) || 0) + 1);
  }

  const authorCounts = [...perAuthor.values()];
  const dupes = await CommentModel.aggregate<{ n: number }>([
    { $group: { _id: "$redditId", n: { $sum: 1 } } },
    { $match: { n: { $gt: 1 } } },
    { $count: "n" },
  ]);

  const mentionRows = await MultipassEntityMention.countDocuments();
  const mentionRowsWithCommentId = await MultipassEntityMention.countDocuments({
    commentId: { $ne: null },
  });
  const commentsWithMentionRows = joined.filter((c) => mentionCommentIds.has(c._id)).length;

  const report = {
    generatedAt: new Date().toISOString(),
    totals: {
      posts: totalPosts,
      comments: totalComments,
      commentsWithoutPost: totalComments - joined.length,
      duplicateRedditIds: dupes[0]?.n ?? 0,
      botOrDeletedComments: botOrDeleted,
      uniqueAuthors: perAuthor.size,
      authorsWith10PlusComments: authorCounts.filter((n) => n >= 10).length,
      authorsWith5PlusComments: authorCounts.filter((n) => n >= 5).length,
    },
    mentionCoverage: {
      mentionRows,
      mentionRowsWithCommentId,
      distinctCommentIdsInMentionRows: mentionCommentIds.size,
      scrapedCommentsWithMentionRows: commentsWithMentionRows,
      shareOfScrapedComments: joined.length ? commentsWithMentionRows / joined.length : 0,
      note:
        "Most mention rows point at comments the multipass pipeline fetched live and never stored in `comments`. " +
        "The join covers a small share of the scraped corpus, so the signals run does its own NER pass over `comments` (scripts/ner_comments.py).",
    },
    postsBySubreddit: Object.fromEntries(postsBySub),
    commentsBySubreddit: bySub,
    commentsByMonth: Object.fromEntries(Object.entries(byMonth).sort()),
  };

  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
  logger.info(`Corpus audit written to ${outPath}`);
  console.log(JSON.stringify(report.totals, null, 2));
  console.log(JSON.stringify(report.mentionCoverage, null, 2));
  await databaseService.disconnect();
}

if (require.main === module) {
  main().catch((error) => {
    logger.error("Corpus audit failed", { error });
    process.exit(1);
  });
}
