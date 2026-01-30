"""
Iceberg Data Remediation Service.

A local CLI tool for validating and correcting historical market data
in the Iceberg production database using Breeze Historical API.

Usage:
    python -m iceberg_remediation validate --symbol nifty --from-date 2026-01-15 --to-date 2026-01-20
    python -m iceberg_remediation remediate --symbol nifty --from-date 2026-01-15 --to-date 2026-01-20 --dry-run
    python -m iceberg_remediation status
"""
__version__ = "1.0.0"
__author__ = "Iceberg Team"
