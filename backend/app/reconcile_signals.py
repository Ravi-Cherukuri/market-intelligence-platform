"""Explicit operator command to reconcile derived semantic signal duplicates."""

from __future__ import annotations

import argparse

from app.ai.openai_client import OpenAIIntelligenceClient
from app.config import get_settings
from app.database import SessionLocal
from app.services.signals import reconcile_semantic_duplicates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("company_id", help="Company whose derived signals should be reconciled")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY is required for semantic signal reconciliation")
    with SessionLocal() as session:
        merged = reconcile_semantic_duplicates(
            session,
            args.company_id,
            OpenAIIntelligenceClient(settings.openai_api_key),
        )
        session.commit()
    print(f"semantic_signals_merged={merged}")


if __name__ == "__main__":
    main()
