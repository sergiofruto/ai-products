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


def cmd_serve() -> None:
    import threading

    import web
    local = threading.local()  # one SQLite connection per server thread

    def conn_factory():
        if not hasattr(local, "conn"):
            local.conn = db.connect(config.DB_PATH)
        return local.conn

    app = web.create_app(conn_factory, lambda: llm.from_config(conn_factory()))
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, threaded=True)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="news-desk")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="build today's paper")
    sub.add_parser("serve", help="serve the web UI on 127.0.0.1")
    args = p.parse_args(argv)
    _setup_logging()
    if args.cmd == "serve":
        cmd_serve()
    else:
        print(json.dumps(cmd_run()))


if __name__ == "__main__":
    main()
