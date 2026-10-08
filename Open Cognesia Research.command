#!/bin/zsh
cd -- "${0:A:h}" || exit 1
exec .venv/bin/python scripts/start_research_agent.py
