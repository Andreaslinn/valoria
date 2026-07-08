"""Experimental consensus v1 alias.

This wraps the existing non-mutating consensus implementation under the
explicit future engine name requested for the multimotor registry.
"""
from __future__ import annotations

from domain.valuation.engines.valoria_consensus import ValoriaConsensusEngine


class ValoriaConsensusV1Engine(ValoriaConsensusEngine):
    name = "valoria_consensus_v1"
