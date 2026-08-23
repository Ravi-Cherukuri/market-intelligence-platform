"""Idempotent pilot bootstrap; safe to run on every API container start."""

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import Company, RetentionPolicy, WhatsAppChannel


DEFAULT_RETENTION = {
    "raw_messages": 730,
    "media": 730,
    "transcripts": 1825,
    "structured_observations": 1825,
    "reports": None,
    "audit_records": 1825,
}


def seed() -> str:
    settings = get_settings()
    with SessionLocal() as session:
        company = session.scalar(select(Company).order_by(Company.created_at))
        if company is None:
            company = Company(name=settings.company_name)
            session.add(company)
            session.flush()
        if settings.whatsapp_phone_number_id:
            channel = session.scalar(
                select(WhatsAppChannel).where(
                    WhatsAppChannel.phone_number_id == settings.whatsapp_phone_number_id
                )
            )
            if channel is None:
                session.add(
                    WhatsAppChannel(
                        company_id=company.id,
                        phone_number_id=settings.whatsapp_phone_number_id,
                    )
                )
        for data_type, days in DEFAULT_RETENTION.items():
            exists = session.scalar(
                select(RetentionPolicy.id).where(
                    RetentionPolicy.company_id == company.id,
                    RetentionPolicy.data_type == data_type,
                )
            )
            if not exists:
                session.add(
                    RetentionPolicy(
                        company_id=company.id,
                        data_type=data_type,
                        retention_days=days,
                    )
                )
        session.commit()
        return company.id


if __name__ == "__main__":
    print(seed())
