"""
Single entry point for the pipeline.

    python -m pipeline run --stage all            # ingest -> clean -> load -> transform
    python -m pipeline run --stage ingest|clean|load|transform
    python -m pipeline run --stage load --incremental     # only re-merge recent order dates

Every stage logs row counts and its own runtime; a summary table with
per-stage timings is printed at the end and appended to logs/runs.jsonl.
"""

from __future__ import annotations

import argparse
import json
import logging
import resource
import sys
import time
from datetime import datetime

from pipeline import config

STAGES = ["ingest", "clean", "load", "transform"]
logger = logging.getLogger("pipeline")


def setup_logging() -> None:
    config.LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(config.LOG_DIR / "pipeline.log")):
        h.setFormatter(fmt)
        root.addHandler(h)


def run_stage(stage: str, args) -> dict:
    # imported lazily so `--stage clean` works without a database driver/connection
    if stage == "ingest":
        from pipeline import ingest
        counts = ingest.run(chunk_size=args.chunk_size)
        return {"rows": sum(counts.values())}
    if stage == "clean":
        from pipeline import clean
        rep = clean.run()
        return {"rows": sum(rep.rows_in.values()),
                "rejected": sum(sum(r.values()) for r in rep.rejected.values())}
    if stage == "load":
        from pipeline import load
        return load.run(incremental=args.incremental, lookback_days=args.lookback_days)
    if stage == "transform":
        from pipeline import transform
        return transform.run()
    raise ValueError(stage)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one or all pipeline stages")
    run.add_argument("--stage", choices=STAGES + ["all"], default="all")
    run.add_argument("--incremental", action="store_true",
                     help="load: only merge orders on/after (watermark - lookback)")
    run.add_argument("--lookback-days", type=int, default=3,
                     help="incremental: re-merge this many days before the watermark "
                          "to pick up late-arriving rows (default 3)")
    run.add_argument("--chunk-size", type=int, default=config.CHUNK_SIZE)
    args = ap.parse_args(argv)

    setup_logging()
    stages = STAGES if args.stage == "all" else [args.stage]
    timings, t_all = {}, time.perf_counter()
    for stage in stages:
        logger.info("=== stage: %s ===", stage)
        t0 = time.perf_counter()
        try:
            stats = run_stage(stage, args)
        except Exception as exc:  # clear, single-line error + full traceback in the log file
            logger.error("stage '%s' failed: %s: %s", stage, type(exc).__name__, exc)
            logging.getLogger().handlers[1].handle(logging.makeLogRecord(
                {"msg": "traceback", "exc_info": sys.exc_info(), "levelno": logging.ERROR,
                 "levelname": "ERROR"}))
            return 1
        timings[stage] = {"seconds": round(time.perf_counter() - t0, 2), **(stats or {})}
        logger.info("=== %s finished in %.1fs ===", stage, timings[stage]["seconds"])
    total = round(time.perf_counter() - t_all, 2)

    logger.info("Run summary:")
    for stage, t in timings.items():
        logger.info("  %-10s %8.1fs  %s", stage, t["seconds"],
                    {k: v for k, v in t.items() if k != "seconds"})
    logger.info("  %-10s %8.1fs", "TOTAL", total)
    # ru_maxrss is in KiB on Linux: the peak memory of this Python process
    peak_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    logger.info("  peak memory (RSS) of the pipeline process: %s MB", peak_mb)
    with open(config.LOG_DIR / "runs.jsonl", "a") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                            "stage": args.stage, "incremental": args.incremental,
                            "total_seconds": total, "peak_rss_mb": peak_mb,
                            "stages": timings}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
