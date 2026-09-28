"""Offline GLiNER pass over exported comments for the commercial-posting-signals study.

Reads  data/commercial-signals/private/comments.jsonl  (from `npm run signals:export`)
Writes data/commercial-signals/private/ner.jsonl        (one line per comment: {"id", "ents"})

Local only; never touches MongoDB. Resumable: ids already in ner.jsonl are skipped.
Labels and thresholds mirror src/config/pipeline.config.ts. Set GLINER_MODEL to override
the model (default is the same base model the sidecar loads).

    python3 -m venv ~/ner-venv && ~/ner-venv/bin/pip install gliner tiktoken sentencepiece protobuf
    ~/ner-venv/bin/python scripts/ner_comments.py [limit]
"""
import json
import os
import sys
import time

import torch
from gliner import GLiNER

torch.set_num_threads(int(os.getenv("THREADS", "8")))
MODEL = os.getenv("GLINER_MODEL", "urchade/gliner_multi-v2.1")
LABELS = ["knife brand", "knife model", "knife steel"]
THRESH = {
    "knife brand": float(os.getenv("GLINER_THRESHOLD_BRAND", "0.35")),
    "knife model": float(os.getenv("GLINER_THRESHOLD_MODEL", "0.30")),
    "knife steel": float(os.getenv("GLINER_THRESHOLD_STEEL", "0.20")),
}
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else None
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PRIV = os.path.join(ROOT, "data", "commercial-signals", "private")
SRC = os.path.join(PRIV, "comments.jsonl")
OUT = os.path.join(PRIV, "ner.jsonl")
BATCH = 16


def main() -> None:
    done = set()
    if os.path.exists(OUT):
        with open(OUT) as f:
            for line in f:
                done.add(json.loads(line)["id"])

    with open(SRC) as f:
        rows = [json.loads(l) for l in f]
    rows = [r for r in rows if r["id"] not in done]
    if LIMIT:
        rows = rows[:LIMIT]
    print(f"to process: {len(rows)} (already done {len(done)})", flush=True)

    model = GLiNER.from_pretrained(MODEL)
    model.eval()
    t0 = time.time()
    with open(OUT, "a") as out, torch.inference_mode():
        for i in range(0, len(rows), BATCH):
            batch = rows[i : i + BATCH]
            texts = [r["content"][:2000] for r in batch]
            preds = model.batch_predict_entities(texts, LABELS, threshold=min(THRESH.values()))
            for r, ents in zip(batch, preds):
                keep = [
                    {"text": e["text"], "label": e["label"], "score": round(e["score"], 3)}
                    for e in ents
                    if e["score"] >= THRESH[e["label"]]
                ]
                out.write(json.dumps({"id": r["id"], "ents": keep}) + "\n")
            if (i // BATCH) % 20 == 0:
                el = time.time() - t0
                n = i + len(batch)
                print(f"{n}/{len(rows)} {el:.0f}s {n / max(el, 1):.1f}/s", flush=True)
    print("done", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
