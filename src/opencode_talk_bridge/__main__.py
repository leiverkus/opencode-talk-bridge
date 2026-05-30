"""CLI entrypoint: load config, wire up clients, run the bridge.

Usable directly (``python -m opencode_talk_bridge``) or via the
``opencode-talk-bridge`` console script. Designed to run under launchd; see
``deploy/`` and the README.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from .bridge import Bridge
from .config import Config, ConfigError, load_dotenv
from .opencode import OpenCodeClient, wait_for_healthy
from .scheduler import TaskStore
from .sessions import SessionStore
from .status import StatusWriter
from .stt import STTClient
from .talk import TalkGateway
from .tts import TTSClient


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="opencode-talk-bridge", description=__doc__)
    p.add_argument("--env-file", default=".env", help="path to a .env file (default: .env)")
    p.add_argument("--check", action="store_true", help="validate config + check OpenCode health, then exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    load_dotenv(args.env_file)

    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("opencode_talk_bridge")

    opencode = OpenCodeClient(
        config.opencode_url,
        username=config.opencode_username,
        password=config.opencode_password,
        directory=config.opencode_directory,
        default_model=config.opencode_model,
    )

    if args.check:
        healthy = opencode.health()
        print(f"config OK; OpenCode at {config.opencode_url}: {'healthy' if healthy else 'UNREACHABLE'}")
        opencode.close()
        return 0 if healthy else 1

    status = StatusWriter(config.status_file)
    if not wait_for_healthy(opencode, attempts=3, delay=2.0):
        log.warning("OpenCode at %s is not reachable yet — starting anyway", config.opencode_url)
        status.update(state="opencode_down", opencode_healthy=False)

    gateway = TalkGateway(config.talk)
    store = SessionStore(config.db_path)

    stt = (
        STTClient(
            config.stt_url, api_key=config.stt_key, model=config.stt_model, language=config.stt_language
        )
        if config.stt_url
        else None
    )
    tts = (
        TTSClient(config.tts_url, api_key=config.tts_key, model=config.tts_model, voice=config.tts_voice)
        if config.tts_url
        else None
    )
    task_store = TaskStore(config.db_path)

    bridge = Bridge(config, gateway, opencode, store, status, stt=stt, tts=tts, task_store=task_store)

    def _handle_signal(signum, _frame):
        log.info("received signal %s", signum)
        bridge.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    try:
        bridge.run()
    finally:
        gateway.close()
        store.close()
        task_store.close()
        opencode.close()
        if stt:
            stt.close()
        if tts:
            tts.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
