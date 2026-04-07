from __future__ import annotations

import argparse

from app.demo_server import run_demo_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the multi-agent ReAct demo")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", default=8080, type=int, help="Server port")
    args = parser.parse_args()
    run_demo_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
