# AWS pilot architecture

The pilot is intentionally one deployable monolith on one Graviton EC2 host in
Mumbai. Caddy terminates TLS and routes to the Next.js administrator interface
and FastAPI webhook. The API, worker, PostgreSQL and Caddy remain one Docker
Compose release even though they run as separate processes.

The single host is a deliberate early-testing constraint, not a production HA
claim. Host or Availability Zone failure can cause several hours of downtime.
Daily EBS snapshots retain seven recovery points. A daily custom-format
PostgreSQL dump is validated with `pg_restore --list`, uploaded to the private
versioned S3 bucket, and retained for 35 days. An hourly metric alarms when the
latest verified dump is older than 26 hours or the metric stops arriving.

The 2 GiB `t4g.small` profile supports text, voice notes and photos using
external AI APIs. Media downloads are streamed into a 25 MB bounded buffer and
validated against MIME and file signatures before storage or AI submission.

Automated releases run only additive database migrations. The build rejects
destructive Alembic operations, creates a tested logical backup before every
post-pilot migration, and health-checks both the candidate and any image
rollback. Schema-destructive changes require a separately reviewed maintenance
and restore window. Every future automated migration must explicitly declare
`AUTOMATED_ROLLBACK_SAFE = True` after an expand/contract compatibility review;
the build also rejects known destructive operations and required columns that
lack a backward-compatible server default.
Document attachments, local model execution and continuous ClamAV scanning are
deferred for the explicitly accepted pilot risk. Resize to `t4g.medium` or
split scanning before adding those workloads.

GoDaddy retains DNS control. After deployment, the `fieldintel` A record for
`svabhu.com` points to the retained Elastic IP. Port 80 exists only for ACME and
redirects; application and Meta traffic use HTTPS. Port 22 is never opened.

The application stack is deployed in `ap-south-1`. The separate AWS Budgets
stack is deployed in `us-east-1`, reflecting the service's global control
plane. Budget messages are warnings, not hard spending limits.

Application images are built for `linux/arm64`, pushed to an immutable private
ECR repository, and deployed by digest. The instance role can pull releases but
cannot push or overwrite them. Runtime S3 access is prefix-scoped and has no
object-deletion permission.
