// src/commands/refresh-comments.ts
//
// One-off or backlog run of the comment refresh that the scheduler also runs after every
// scrape. See services/comment-refresh.service.ts.
//
//   npm run signals:refresh -- [--subs knives,knifeclub] [--min-age-hours 48] [--limit N] [--dry-run]

import minimist from "minimist";
import { unifiedDatabaseService as databaseService } from "../services/mongoose-database.service";
import { SUBREDDITS, commentRefreshConfig } from "../config/reddit.config";
import {
  RefreshSelection,
  countPendingRefresh,
  refreshStaleComments,
} from "../services/comment-refresh.service";
import logger from "../services/logger.service";

async function main() {
  const args = minimist(process.argv.slice(2));
  const sel: RefreshSelection = {
    subs: args.subs
      ? String(args.subs).split(",").map((s) => s.trim()).filter(Boolean)
      : SUBREDDITS.map((s) => s.name),
    minAgeHours: Number(args["min-age-hours"] ?? commentRefreshConfig.minAgeHours),
    limit: args.limit ? Number(args.limit) : undefined,
  };

  await databaseService.connect();
  if (args["dry-run"]) {
    const pending = await countPendingRefresh(sel);
    logger.info(`Comment refresh dry run: ${pending} posts pending`, { ...sel });
  } else {
    await refreshStaleComments(sel);
  }
  await databaseService.disconnect();
}

if (require.main === module) {
  main().catch((error) => {
    logger.error("Comment refresh failed", { message: (error as Error).message, stack: (error as Error).stack });
    process.exit(1);
  });
}
