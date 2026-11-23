"""Decode control and typed RF records; session code still enforces negotiated support."""

from pydantic import TypeAdapter

from . import control_v2, crypto_benchmark_v2, rf_events_v2

ADAPTER = TypeAdapter(control_v2.WireRecord | rf_events_v2.RFEvent | crypto_benchmark_v2.Event)
