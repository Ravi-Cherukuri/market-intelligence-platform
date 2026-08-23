# Pilot infrastructure

This directory contains code-only infrastructure for
`fieldintel.svabhu.com`. Creating or updating live AWS resources is a separate,
explicitly approved step.

## Stack layout

- `cloudformation/pilot.yaml` - Mumbai VPC, EC2 host, EIP, encrypted storage,
  ECR, SSM access, snapshots, logs and alarms.
- `cloudformation/budget.yaml` - account-level monthly cost notifications,
  deployed in `us-east-1`.
- `architecture.md` - design constraints and recovery limits shared by both
  templates.

## Deployment order

1. Validate both templates locally.
2. Create non-executed CloudFormation change sets.
3. Review the change sets and estimated charges.
4. After explicit approval, execute the budget stack and then the pilot stack.
5. Confirm the SNS email subscription.
6. Add a GoDaddy A record: host `fieldintel`, value from the
   `ElasticIpAddress` stack output, TTL 600 seconds.
7. Deploy the signed application release and configure runtime secrets.
8. Confirm HTTPS health before entering the Meta webhook URL.

The templates never contain application-provider credentials. Runtime secrets
will be configured through the approved AWS secret workflow immediately before
the first live deployment.
