# Cutover and Rollback Checklist

## Pre-cutover

- [ ] API and dashboard images pushed to ECR
- [ ] ECS services healthy (2 tasks each)
- [ ] ALB target groups healthy
- [ ] RDS reachable from API (`/health/db` passes)
- [ ] Secrets loaded successfully in tasks

## Functional smoke tests

- [ ] Signup flow with OTP works
- [ ] Login flow with OTP works
- [ ] Session persists and protected routes enforce auth
- [ ] Upload via local file works
- [ ] Upload via presigned URL works
- [ ] Analysis runs to completion
- [ ] Report builder jobs generate and export

Optional quick check script:

- `python scripts/aws/smoke_production.py --base-url https://<your-domain>`

## Observability checks

- [ ] API logs visible in CloudWatch
- [ ] Dashboard logs visible in CloudWatch
- [ ] No sustained 5xx on ALB during smoke tests

## DNS cutover

1. Lower Route53 TTL before cutover (e.g., 60s).
2. Point production alias record to ALB.
3. Monitor error rates and p95 latency for 30-60 minutes.

## Rollback plan

If issues occur:

1. Revert Route53 alias to previous stable ALB/service.
2. Roll back ECS service to previous task definition revision.
3. Restore DB from snapshot only for data corruption cases.
4. Keep incident notes and postmortem actions.
