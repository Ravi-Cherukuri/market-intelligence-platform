# AWS pilot architecture

The pilot is intentionally one deployable monolith on one Graviton EC2 host in
Mumbai. Caddy terminates TLS and routes to the Next.js administrator interface
and FastAPI webhook. The API, worker, PostgreSQL and Caddy remain one Docker
Compose release even though they run as separate processes.

The single host is a deliberate early-testing constraint, not a production HA
claim. Host or Availability Zone failure can cause several hours of downtime.
Daily EBS snapshots retain seven recovery points; logical PostgreSQL dumps must
also be written to the private versioned S3 bucket before live field testing.

The 2 GiB `t4g.small` profile supports text, voice notes and photos using
external AI APIs. Document attachments, local model execution and continuous
ClamAV scanning are deferred. Resize to `t4g.medium` or split scanning before
adding those workloads.

GoDaddy retains DNS control. After deployment, the `fieldintel` A record for
`svabhu.com` points to the retained Elastic IP. Port 80 exists only for ACME and
redirects; application and Meta traffic use HTTPS. Port 22 is never opened.

The application stack is deployed in `ap-south-1`. The separate AWS Budgets
stack is deployed in `us-east-1`, reflecting the service's global control
plane. Budget messages are warnings, not hard spending limits.
