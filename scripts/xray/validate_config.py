#!/usr/bin/env python3
"""Shared Xray config usability gate (stdlib only).

Usage: validate_config.py <config.json>
Exit 0 when the config is structurally usable, 1 otherwise.

Checks:
  - file parses as JSON object;
  - `outbounds` is a non-empty list;
  - `inbounds` is a non-empty list with at least one entry carrying a
    numeric `port` and a `protocol` string;
  - every balancer has a non-empty `selector` matching outbound tags;
  - every balancer strategy type is one Xray supports for balancers;
  - every routing rule `balancerTag` matches an existing balancer `tag`;
  - when any balancer uses leastPing/leastLoad, `observatory.subjectSelector`
    covers all balancer selectors and `observatory.probeUrl` is non-empty
    (probes need targets and a URL to probe).
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
    inbounds = cfg.get("inbounds")
    if not isinstance(inbounds, list) or len(inbounds) == 0:
        return fail("inbounds is empty or missing")
    if not any(isinstance(i, dict) and isinstance(i.get("port"), (int, float)) and isinstance(i.get("protocol"), str) for i in inbounds):
        return fail("no inbound with numeric port and protocol")
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
    balancer_tags = set()
    needs_probes = False
    for b in balancers:
        if not isinstance(b, dict):
            return fail("balancer entry is not an object")
        btag = b.get("tag")
        if isinstance(btag, str):
            balancer_tags.add(btag)
        selector = b.get("selector", [])
        if not isinstance(selector, list) or len(selector) == 0:
            return fail("balancer %r has empty or missing selector" % (btag,))
        for sel in selector:
            if sel not in tags:
                return fail("selector %r matches no outbound tag" % (sel,))
        strategy = b.get("strategy")
        stype = strategy.get("type") if isinstance(strategy, dict) else None
        if stype not in ALLOWED_STRATEGIES:
            return fail("strategy type %r not in %s" % (stype, sorted(ALLOWED_STRATEGIES)))
        if stype in ("leastPing", "leastLoad"):
            needs_probes = True
    rules = routing.get("rules", [])
    if not isinstance(rules, list):
        return fail("rules is not a list")
    for r in rules:
        if isinstance(r, dict) and "balancerTag" in r:
            if r["balancerTag"] not in balancer_tags:
                return fail("rule balancerTag %r matches no balancer tag" % (r["balancerTag"],))
    if needs_probes:
        obs = cfg.get("observatory")
        subjects = obs.get("subjectSelector") if isinstance(obs, dict) else None
        if not isinstance(subjects, list):
            return fail("observatory.subjectSelector missing - required by leastPing/leastLoad")
        missing = sorted(set(sel for b in balancers for sel in b.get("selector", []) if sel not in subjects))
        if missing:
            return fail("observatory.subjectSelector misses %s" % (missing,))
        probe = obs.get("probeUrl")
        if not isinstance(probe, str) or not probe.strip():
            return fail("observatory.probeUrl missing or empty - required by leastPing/leastLoad")
    print("validate_config: usable (%d outbounds, %d balancers)" % (len(outbounds), len(balancers)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
