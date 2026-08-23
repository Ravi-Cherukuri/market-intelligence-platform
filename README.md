# Agricultural Market Intelligence Pilot

A WhatsApp-first, evidence-led market-intelligence platform for agricultural inputs. Registered field employees send text, voice notes, and photographs to a company WhatsApp Business number. The system preserves the original evidence, extracts structured observations, corroborates repeated signals, and makes state-level intelligence available to administrators.

## Current pilot capabilities

- Official Meta WhatsApp Cloud API webhook verification and HMAC authentication
- Destination-number company segregation and sender-number employee validation
- Content-free audit handling for unknown senders
- Idempotent inbound processing using Meta message IDs
- Rolling 30-minute field conversations with `Done` and `New report`
- Text, audio, image, and location message persistence; documents are rejected in the pilot
- Background media retrieval, size controls, and tenant-scoped S3 storage
- OpenAI transcription, image interpretation, structured extraction, and adaptive model routing
- Weak/strong signal aggregation using distinct employee evidence
- Append-only competition price history with separate farmer and channel-net prices
- Preview-first CSV/XLSX employee, product, and price imports
- Configurable retention policies and immutable audit events
- Responsive administrator dashboard and placeholder HTTP Basic administrator gate
- Docker Compose deployment for a low-cost AWS EC2 pilot

## Repository shape

```text
app/                         Next.js administrator web application
backend/app/api/             FastAPI HTTP boundaries
backend/app/domain/          Pure business policies
backend/app/services/        Persistence-coordinating use cases
backend/app/integrations/    Meta, S3, malware, and provider adapters
backend/app/ai/              Model routing and strict AI output schemas
backend/tests/               Acceptance and security-focused tests
backend/migrations/          Alembic schema history
docker-compose.yml           Single-VM pilot runtime
```

The API and background worker are separate processes from one monolithic codebase. This keeps slow media and AI calls away from the webhook response without introducing microservices.

The 2 GiB pilot host intentionally does not run ClamAV. Meta-delivered photos
and voice notes are stored but never decoded or executed locally. Document
attachments remain disabled until the host or scanning architecture is expanded.

## Local development

1. Copy `.env.example` to `.env` and keep `.env` private.
2. Install web dependencies with `pnpm install`.
3. Create `backend/.venv` and install `backend/requirements.txt`.
4. Run the web app with `pnpm dev`.
5. Run the API from `backend/` with `uvicorn app.main:app --reload`.

Local development defaults to SQLite. The hosted pilot uses PostgreSQL through Docker Compose. Production startup deliberately fails when placeholder credentials or required provider settings remain.

## Verification

```bash
pnpm test
pnpm build
cd backend
.venv/bin/python -m pytest
.venv/bin/alembic upgrade head
```

Tests use fake provider boundaries and never make paid OpenAI or WhatsApp calls.

## Credentials required for live testing

Do not paste secrets into source files or commit them. Put them only in `.env` or the eventual AWS secret store.

- Meta Graph API version
- WhatsApp phone-number ID
- WhatsApp access token
- Meta app secret
- A private webhook verification token
- OpenAI API key
- AWS region and S3 bucket
- A strong replacement for the placeholder administrator password

## Trust model

Field content is evidence, never instruction. AI calls receive no tools or configuration authority. Every observation and signal retains source-message IDs, employee context, model identity, prompt/schema version, and confidence. Unknown senders do not have message content or media retained.
