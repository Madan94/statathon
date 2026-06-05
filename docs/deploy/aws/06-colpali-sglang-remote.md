# Remote ColPali + SGLang on AWS — Console Setup (No CLI)

Run **ColPali** (port **8100**) and **SGLang** (port **30000**) on one **g5.xlarge** GPU instance. Keep **FastAPI + dashboard on your Windows PC** and point `.env` at the instance IP.

**Region:** **eu-north-1** (Stockholm) — matches your S3 bucket.

---

## Architecture

```
Windows PC (API :8000, Dashboard :3000)
    │  COLPALI_ENDPOINT → :8100/extract
    │  SGLANG_ENDPOINT  → :30000
    ▼
EC2 g5.xlarge (24 GB VRAM)
    ├── Docker: colpali  (vidore/colpali-v1.2, ~4 GB)
    └── Docker: sglang   (Qwen2.5-3B-Instruct, ~6–8 GB)
    └── EBS /data/model/cache  (HuggingFace weights)
```

Do **not** use Qwen2.5-**7B** on the same GPU as ColPali.

---

## Part A — AWS Console (one-time)

### Step 1 — IAM role for Session Manager (optional but useful)

1. Open **IAM** → **Roles** → **Create role**.
2. Trusted entity: **AWS service** → **EC2**.
3. Attach policy: **AmazonSSMManagedInstanceCore**.
4. Name: `statathon-gpu-ec2-role` → **Create role**.
5. Open the role → **Create instance profile** (if prompted) or note the role for Step 4.

### Step 2 — Security group

1. Open **EC2** → **Security Groups** → **Create security group**.
2. Name: `statathon-gpu-sidecars`, VPC: **default**.
3. **Inbound rules** (replace `YOUR.IP.ADDRESS` with your public IP from https://ifconfig.me):

| Type | Port | Source | Purpose |
|------|------|--------|---------|
| Custom TCP | 8100 | `YOUR.IP.ADDRESS/32` | ColPali |
| Custom TCP | 30000 | `YOUR.IP.ADDRESS/32` | SGLang |
| SSH | 22 | `YOUR.IP.ADDRESS/32` | Optional — only if you use SSH instead of Session Manager |

4. **Outbound:** allow all (default).
5. **Create security group**.

### Step 3 — Key pair (only if using SSH)

1. **EC2** → **Key pairs** → **Create key pair** → name `statathon-gpu`, type `.pem` → download and save safely.

Skip if you will use **Session Manager** only (browser shell, no SSH key).

### Step 4 — Launch g5.xlarge

1. **EC2** → **Instances** → **Launch instances**.
2. Settings:

| Field | Value |
|-------|--------|
| Name | `statathon-gpu-models` |
| AMI | **Deep Learning Base AMI** (Ubuntu 22.04) **or** Amazon Linux 2023 with NVIDIA drivers |
| Instance type | **g5.xlarge** |
| Key pair | Your key (SSH) or **Proceed without** (Session Manager only) |
| Network | Default VPC, **Auto-assign public IP: Enable** |
| Security group | Select `statathon-gpu-sidecars` |
| Storage | **100 GiB** gp3 (root volume) |

3. **Advanced details** → **IAM instance profile**: select `statathon-gpu-ec2-role` (from Step 1).
4. **Launch instance**.
5. Wait until **Instance state = Running**.
6. Copy **Public IPv4 address** (e.g. `51.21.x.x`) — this is your `GPU_HOST` unless you use tunnels.

### Step 5 — Elastic IP (recommended)

Public IP changes on stop/start without Elastic IP.

1. **EC2** → **Elastic IPs** → **Allocate**.
2. **Actions** → **Associate** → select your `statathon-gpu-models` instance.
3. Use this IP as `GPU_HOST` in `.env`.

---

## Part B — On the EC2 instance (browser terminal)

### Connect without CLI

1. **EC2** → **Instances** → select instance → **Connect**.
2. Tab **Session Manager** → **Connect** (opens browser shell).  
   If Session Manager is unavailable: fix IAM role (Step 1) and wait ~5 min after launch.
3. Alternative: tab **EC2 Instance Connect** → **Connect**.

### Install Docker + NVIDIA Container Toolkit

Run on the instance (Ubuntu DL AMI example):

```bash
# Docker
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER
newgrp docker

# NVIDIA Container Toolkit — follow NVIDIA docs if not preinstalled:
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
nvidia-smi   # must show A10G GPU
```

### Clone repo and deploy models

```bash
sudo mkdir -p /data/model/cache
sudo chown -R $USER:$USER /data/model/cache

git clone <YOUR_REPO_URL> statathon
cd statathon

export GPU_MODEL_CACHE=/data/model/cache
# optional: export HF_TOKEN=<huggingface-token>

bash scripts/aws/ec2-gpu-bootstrap.sh
```

First run downloads models (**15–30 minutes**). The script waits until both `/health` endpoints respond.

### Manual commands (if you prefer)

```bash
cd statathon
export GPU_MODEL_CACHE=/data/model/cache
docker compose -f docker-compose.gpu.yml --profile gpu build colpali sglang
docker compose -f docker-compose.gpu.yml --profile gpu up -d colpali sglang
curl http://localhost:8100/health
curl http://localhost:30000/health
nvidia-smi
```

---

## Part C — Windows PC configuration

Your repo `.env` is already set for SSM/tunnel style (`127.0.0.1`). For **direct public IP** (simplest with Console-only setup):

Edit [`.env`](../../../.env):

```ini
GPU_HOST=<ELASTIC_IP_OR_PUBLIC_IP>

COLPALI_ENDPOINT=http://<ELASTIC_IP>:8100/extract
SGLANG_ENDPOINT=http://<ELASTIC_IP>:30000

VLM_BACKEND=colpali
PDF_PARSER=colpali
COLPALI_IN_PROCESS=false
COLPALI_ALLOW_SIDECAR=true
COLPALI_TIMEOUT=600

SGLANG_BACKEND=sglang
SGLANG_MODEL=Qwen/Qwen2.5-3B-Instruct
SGLANG_TIMEOUT=300
SGLANG_DECOMPOSED=true
```

See also [`.env.gpu-remote.example`](../../../.env.gpu-remote.example).

Restart local API:

```powershell
cd d:\statathon-hack\statathon\api
..\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Part D — Verify from Windows

```powershell
cd d:\statathon-hack\statathon
$host = "<ELASTIC_IP>"
Invoke-RestMethod "http://${host}:8100/health"
Invoke-RestMethod "http://${host}:30000/health"
.\scripts\aws\verify_gpu_endpoints.ps1 -GpuHost $host
```

Then use Report Builder or:

```powershell
pytest tests/test_template_engine/ -m live_vlm -q
pytest tests/test_template_engine/ -m live_sglang -q
```

---

## Part E — Daily workflow

| Action | Where |
|--------|--------|
| Start GPU instance | EC2 Console → Instance → **Start** |
| Stop GPU (save money) | EC2 → **Stop** (EBS keeps model cache) |
| Start local API + dashboard | Your PC (README Step 4) |
| Check models healthy | Browser: `http://<IP>:8100/health` and `:30000/health` |

**Cost:** g5.xlarge on-demand ≈ **$1–1.5/hour** in eu-north-1. Stop when not developing.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Session Manager unavailable | Attach IAM role `AmazonSSMManagedInstanceCore`; reboot instance |
| Connection refused from Windows | Security group must allow **your current IP** on 8100 and 30000 |
| ColPali/SGLang unhealthy on EC2 | `docker compose -f docker-compose.gpu.yml --profile gpu logs colpali sglang` |
| OOM / CUDA OOM | Use Qwen **3B** only; lower `SGLANG_MEM_FRACTION_STATIC=0.38` in compose |
| Slow first start | Normal — models download to `/data/model/cache` |

---

## Repo files (already in this project)

| File | Purpose |
|------|---------|
| [docker/Dockerfile.colpali](../../../docker/Dockerfile.colpali) | ColPali sidecar, CUDA torch, port 8100 |
| [docker/Dockerfile.sglang](../../../docker/Dockerfile.sglang) | SGLang server, port 30000 |
| [docker-compose.gpu.yml](../../../docker-compose.gpu.yml) | Both services + shared model cache volume |
| [scripts/aws/ec2-gpu-bootstrap.sh](../../../scripts/aws/ec2-gpu-bootstrap.sh) | Build, start, health-wait on EC2 |

Optional CLI helpers (`launch_gpu_ec2.ps1`) exist but **this guide uses Console only**.

---

## Related

- [03-gpu-worker.md](./03-gpu-worker.md) — different path (`INFERENCE_MODE=remote` for analysis)
- [template_engine/README.md](../../../template_engine/README.md) — template engine GPU docs
