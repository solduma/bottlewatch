"""Backtest data sources.

This module is separate from `app/ingest/` because price data is
fundamentally different from signal data: prices are pulled on
demand for an analytical job, not upserted nightly. The
`PriceProvider` protocol keeps the backtest job decoupled from the
price-source implementation.
"""
