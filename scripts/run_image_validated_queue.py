#!/usr/bin/env python3
"""AURA3 production queue entrypoint.

Production alternates between DeepSeek and Amazon Nova 2 Lite while preserving the same
strict current-design image rulebook, resilience protections, image-grounded captions,
business/semantic gates, Founder approval, and publishing authority.
"""
from provider_rotation import main


if __name__ == "__main__":
    raise SystemExit(main())
