#!/usr/bin/env python3
"""Shared Xray config usability gate (stdlib only).

Usage: validate_config.py <config.json>
Exit 0 when the config is structurally usable, 1 otherwise.

Checks:
  - file parses as JSON object;
  - `outbounds` is a non-empty list;
  - every balancer `selector` entry matches an outbound tag;
  - every balancer strategy type is one Xray supports for balancers.
"""
import json
import sys

ALLOWED_STRATEGIES = {"roundRobin", "random", "leastPing", "leastLoad"}


def fail(msg):
    print("validate_config: unusable - " + msg)
    return 1


def main(argv):
    if len(argv) != 2:
        print("usage: validate_config.py <config.json>", file=sys.stderr)
        return 1
    try:
        with open(argv[1]) as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        return fail("%s: %s" % (argv[1], e))
    if not isinstance(cfg, dict):
        return fail("top level is not an object")
    outbounds = cfg.get("outbounds")
    if not isinstance(outbounds, list) or len(outbounds) == 0:
        return fail("outbounds is empty or missing")
    tags = set()
    for o in outbounds:
        if isinstance(o, dict) and isinstance(o.get("tag"), str):
            tags.add(o["tag"])
    routing = cfg.get("routing", {})
    if not isinstance(routing, dict):
        return fail("routing is not an object")
    balancers = routing.get("balancers", [])
    if not isinstance(balancers, list):
        return fail("balancers is not a list")
    for b in balancers:
        if not isinstance(b, dict):
            return fail("balancer entry is not an object")
        for sel in b.get("selector", []):
            if sel not in tags:
                return fail("selector %r matches no outbound tag" % (sel,))
        strategy = b.get("strategy")
        stype = strategy.get("type") if isinstance(strategy, dict) else None
        if stype not in ALLOWED_STRATEGIES:
            return fail("strategy type %r not in %s" % (stype, sorted(ALLOWED_STRATEGIES)))
    print("validate_config: usable (%d outbounds, %d balancers)" % (len(outbounds), len(balancers)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
