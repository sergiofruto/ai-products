"""news-desk command line. `python main.py run` builds today's paper."""
import argparse
import json
import logging
from datetime import datetime, timezone
from functools import partial

import requests

import config
import db
import fetch
import llm
import pipeline


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(config.HERE / "news-desk.log"), logging.StreamHandler()])


def cmd_run() -> dict:
    conn = db.connect(config.DB_PATH)
    llms = llm.from_config(conn)
    sources = fetch.load_sources(config.HERE / "sources.yaml")
    now = datetime.now(timezone.utc)
    fetch_fn = partial(fetch.fetch_all, sources, now, get=requests.get, window_hours=config.CLUSTER_WINDOW_HOURS)
    return pipeline.run(conn, now, llms, fetch_fn)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="news-desk")
    p.add_subparsers(dest="cmd", required=True).add_parser("run", help="build today's paper")
    p.parse_args(argv)
    _setup_logging()
    print(json.dumps(cmd_run()))


if __name__ == "__main__":
    main()
