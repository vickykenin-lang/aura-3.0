#!/usr/bin/env python3
"""Production entrypoint for AURA3 Vastu consultant agent."""
from __future__ import annotations

import vastu_consultant_agent as agent
from vastu_web_research import research


def _research(query: str, minimum_sources: int = 2, max_sources: int = 5):
    return research(query, minimum_sources=minimum_sources, max_sources=max_sources)


agent.ddg_research = _research


if __name__ == "__main__":
    raise SystemExit(agent.main())
