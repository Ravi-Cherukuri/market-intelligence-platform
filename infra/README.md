# Pilot infrastructure

This directory contains code-only infrastructure for
`fieldintel.svabhu.co.in`. Creating or updating live AWS resources is a separate,
explicitly approved step.

## Stack layout

- `cloudformation/pilot.yaml` - Mumbai VPC, EC2 host, EIP, encrypted storage,
  ECR, SSM access, snapshots, logs and alarms.
- `cloudformation/builder.yaml` - isolated on-demand ARM64 CodeBuild project
  with narrowly scoped release-publishing permissions and encrypted logs.
- `cloudformation/budget.yaml` - account-level monthly cost notifications,
  deployed in `us-east-1`.
- `architecture.md` - design constraints and recovery limits shared by both
  templates.
- `scripts/` and `systemd/` - verified database backup/restore and freshness
  monitoring installed by the release workflow.
- `restore-runbook.md` - destructive recovery procedure and smoke checks.

## Deployment order

1. Validate all CloudFormation templates locally.
2. Create non-executed CloudFormation change sets for the pilot and builder stacks.
3. Review the change sets and estimated charges.
4. After explicit approval, execute the budget stack, pilot stack, and then the
   builder stack.
5. Confirm the SNS email subscription.
6. Add a GoDaddy A record: host `fieldintel`, value from the
   `ElasticIpAddress` stack output, TTL 600 seconds.
7. Deploy the checksummed, IAM-controlled application release and configure runtime secrets.

After the reviewed builder stack has been deployed, start a release from a
clean, committed checkout with:

```bash
infra/scripts/start-managed-build.sh fieldintel-pilot-builder
```

The script archives only Git-tracked files, uploads one versioned source object
to the private stack bucket, and starts the on-demand build against that exact
S3 object version. The Git commit and release identifier are non-secret build
inputs. Runtime provider credentials are never sent to CodeBuild. The builder
publishes immutable ARM64 images to the stack repository and a checksummed host
release bundle under `releases/<release-id>/`.

The package checksum detects transfer corruption. Release write access is
restricted by IAM and S3 versioning; the pilot does not yet implement a
separate cryptographic code-signing authority.

Apply `infra/cloudformation/pilot-stack-policy.json` after stack creation and
enable CloudFormation termination protection. Before any reviewed change set
that must replace the host or EBS attachment, run
`sudo /opt/fieldintel/current/scripts/quiesce-host.sh --confirm-stop-fieldintel` through
SSM, confirm the tested backup and unmount succeeded, then temporarily relax
only the affected stack-policy resource for that one change set.
8. Confirm HTTPS health before entering the Meta webhook URL.

The templates never contain application-provider credentials. Runtime secrets
will be configured through the approved AWS secret workflow immediately before
the first live deployment.
