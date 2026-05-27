# GPU Worker Deployment (EC2 Private Subnet)

## Goal

Keep ECS API lightweight while routing heavy model inference to an EC2 GPU worker.

## Recommended shape

- EC2 instance: `g5.xlarge` (or `g4dn.xlarge` for lower cost)
- Placement: private subnet
- Access: SSM Session Manager only (no inbound SSH)
- Runtime: Docker or systemd Python service

## Worker bootstrap

1. Launch Amazon Linux 2023 GPU AMI.
2. Attach IAM role:
   - `AmazonSSMManagedInstanceCore`
   - S3 read/write scoped to app bucket
   - CloudWatch logs write
3. Install runtime:
   - Docker and NVIDIA container toolkit (or Python venv stack)
4. Deploy worker process:
   - Pull source or image
   - Start worker service on port `8080` (internal only)

## API integration contract

Use these env vars on API task definition:

- `INFERENCE_MODE=remote`
- `GPU_WORKER_ENDPOINT=http://<worker-private-ip-or-nlb>:8080`
- `GPU_WORKER_TIMEOUT_SECONDS=900`

In remote mode, API should enqueue/forward heavy inference calls to worker and persist status updates in DB.

## Networking

- `sg-gpu-worker` inbound:
  - TCP 8080 from `sg-ecs-api` only
- Outbound:
  - RDS/Redis/S3/NAT as required by worker pipeline

## Reliability

- Add SQS queue between API and worker for retries and decoupling.
- Configure DLQ for failed jobs.
- Add CloudWatch alarms on:
  - queue depth
  - worker CPU/GPU memory
  - failed jobs rate
