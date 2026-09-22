"""Permanent tunnel-selection package root. Re-exports the T1 seam."""

from factory.net.tunnel_selection import (
    NoTunnelExit,
    Proof,
    ProviderProbe,
    Selection,
    SubscriptionSource,
    TunnelSelector,
)

__all__ = [
    "NoTunnelExit",
    "Proof",
    "ProviderProbe",
    "Selection",
    "SubscriptionSource",
    "TunnelSelector",
]
