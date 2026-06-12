# Deprecated Experimental Skeleton

This package is a disconnected experimental skeleton created before Phase 0B.
It is not registered by `default_engine_registry()` and is not used as the
official multimotor contract source.

Phase 0B keeps it in place only to avoid destructive cleanup in the recovered
checkout. The official contracts live in `domain.valuation.engines.contracts`,
the official registry in `domain.valuation.engines.registry`, and the only
registered engine for this phase is `comparables_legacy`.
