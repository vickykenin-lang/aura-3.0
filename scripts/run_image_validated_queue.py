#!/usr/bin/env python3
"""AURA3 production queue entrypoint.

The actual implementation lives in aura3_resilient_queue.py so production always uses the
strict current-design image validator, persistent dead-image blacklist, structured incident
codes, image-grounded caption semantic gate, automatic rejected/stale cleanup and bounded retries.
Founder approval and publishing authority remain unchanged.
"""
from aura3_resilient_queue import main


if __name__ == "__main__":
    raise SystemExit(main())
