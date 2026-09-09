"""Explicit local demo launcher; run.py remains the production entrypoint."""

import argparse

import uvicorn

from app.demo_integration import create_demo_app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 5: real CSV / existing signals / existing explanation pipeline")
    parser.add_argument("--llm", choices=("live", "fixture"), default="live", help="fixture is offline presentation validation, not a live LLM")
    parser.add_argument("--failure", choices=("none", "no-signal", "llm", "validator"), default="none", help="process-only failure injection")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"Phase 5 Demo: LLM={args.llm}; failure={args.failure}; fixed 2026-08 catalog")
    uvicorn.run(create_demo_app(llm=args.llm, failure=args.failure), host="127.0.0.1", port=args.port)
