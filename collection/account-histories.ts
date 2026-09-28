// src/commands/account-histories.ts
//
// Pull the full public Reddit history (comments and submissions, up to 1,000 each) of the
// accounts listed in data/commercial-signals/private/accounts.csv (from scripts/select_accounts.py).
// Output is one JSON line per account in private/histories.jsonl. Nothing is written to Mongo
// and nothing here leaves the private folder; scripts/account_features.py turns it into
// hashed per-account rows.
//
//   REDDIT_*=... MONGODB_URI=... npm run signals:histories -- [--limit N] [--per-user 1000]

import fs from "fs";
import path from "path";
import minimist from "minimist";
import { redditService } from "../services/reddit.service";
import { unifiedDatabaseService as databaseService } from "../services/mongoose-database.service";
import logger from "../services/logger.service";

const PRIV_DIR = path.resolve(__dirname, "../../data/commercial-signals/private");

export function parseAccountsCsv(text: string): { username: string; author_hash: string; group: string }[] {
  const [header, ...rows] = text.trim().split("\n");
  const cols = header.split(",");
  const iUser = cols.indexOf("author");
  const iHash = cols.indexOf("author_hash");
  const iGroup = cols.indexOf("group");
  return rows
    .map((r) => r.split(","))
    .filter((f) => f[iUser])
    .map((f) => ({ username: f[iUser], author_hash: f[iHash], group: f[iGroup] }));
}

async function main() {
  const args = minimist(process.argv.slice(2));
  const perUser = Number(args["per-user"] ?? 1000);
  const accounts = parseAccountsCsv(fs.readFileSync(path.join(PRIV_DIR, "accounts.csv"), "utf8"));
  const outPath = path.join(PRIV_DIR, "histories.jsonl");

  const done = new Set<string>();
  if (fs.existsSync(outPath)) {
    for (const line of fs.readFileSync(outPath, "utf8").split("\n")) {
      if (line.trim()) done.add(JSON.parse(line).username);
    }
  }
  const todo = accounts.filter((a) => !done.has(a.username)).slice(0, args.limit ? Number(args.limit) : undefined);
  logger.info(`Fetching histories for ${todo.length} accounts (${done.size} already done)`);

  let failed = 0;
  for (const [i, a] of todo.entries()) {
    try {
      const h = await redditService.fetchUserHistory(a.username, perUser);
      const row = h
        ? { ...h, author_hash: a.author_hash, group: a.group, limit: perUser, fetchedAt: new Date() }
        : { username: a.username, author_hash: a.author_hash, group: a.group, unavailable: true, fetchedAt: new Date() };
      fs.appendFileSync(outPath, JSON.stringify(row) + "\n");
      logger.info(
        `[${i + 1}/${todo.length}] ${a.group} ${a.author_hash}: ${h ? `${h.comments.length} comments, ${h.submissions.length} posts` : "unavailable"}`
      );
    } catch (error) {
      failed++;
      logger.error(`History fetch failed for ${a.author_hash}`, { message: (error as Error).message });
    }
  }
  logger.info(`Done: ${todo.length - failed} fetched, ${failed} failed`);
  await databaseService.disconnect();
}

if (require.main === module) {
  main().catch((error) => {
    logger.error("account-histories failed", { message: (error as Error).message, stack: (error as Error).stack });
    process.exit(1);
  });
}
