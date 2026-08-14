# Deploying to EC2

The plan: push this repo to GitHub, clone it on an EC2 box, hand-copy the `.env`
(secrets never travel through git), and `docker compose up`. The public address you get
becomes both the submission URL and the Server URL for ElevenLabs.

## 1. Launch the instance

In the EC2 console:

- **AMI**: Ubuntu Server 24.04 LTS
- **Type**: `t3.medium` (~$0.05/hr — free-tier micros can't hold six containers)
- **Storage**: 20 GB gp3
- **Key pair**: create/download one for SSH
- **Security group**: inbound `22` (SSH, your IP only) and `80` (HTTP, anywhere)

## 2. Install Docker on the box

```bash
ssh -i your-key.pem ubuntu@EC2_PUBLIC_IP
```

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit   # then ssh back in so the group change applies
```

## 3. Clone and configure

```bash
git clone https://github.com/YOUR_USER/voice-agent.git
cd voice-agent
```

Copy the `.env` from your Mac (run this **on your Mac**):

```bash
scp -i your-key.pem .env ubuntu@EC2_PUBLIC_IP:~/voice-agent/.env
```

For a public deployment, change two values in the server's `.env`: a fresh random
`JWT_SECRET` (`openssl rand -hex 32`) and a strong `ADMIN_PASSWORD` — this box is on the
open internet.

## 4. Run it

```bash
docker compose up -d --build     # first build takes a few minutes
```

Then `http://EC2_PUBLIC_IP/` in a browser. Seeding happens automatically on first start.

Sanity checks, run on the box:

```bash
python3 scripts/smoke_test.py    # expects the stack on localhost:80 — works as-is
python3 evals/run_eval.py        # full Golden Dataset against the deployed agent
```

## 5. Point ElevenLabs at it

In the agent's dashboard settings, set the custom LLM Server URL to:

```
http://EC2_PUBLIC_IP/api/agent/v1
```

(ElevenLabs accepts plain HTTP for custom LLM endpoints; if you'd rather have HTTPS,
put the box behind a free Cloudflare proxy or add a caddy container later — not needed
for the demo.)

## Updating after a code change

Manual way, on the box:

```bash
git pull && docker compose up -d --build
```

Automatic way: CI/CD is already wired in `.github/workflows/ci.yml`. Every push runs the
frontend build and the 53-check smoke test on a clean runner; the deploy job then ships to
EC2, but stays dormant until you configure it. To turn it on, in the GitHub repo settings
(Settings → Secrets and variables → Actions):

| Kind | Name | Value |
|---|---|---|
| Variable | `DEPLOY_ENABLED` | `true` |
| Secret | `EC2_HOST` | the instance's public IP |
| Secret | `EC2_SSH_KEY` | contents of your `.pem` key file |
| Secret | `EC2_USER` | `ubuntu` (optional — that's the default) |

From then on, `git push` is the deployment: CI proves the stack, then the deploy job
SSHes in, resets the box to `origin/main`, rebuilds, and health-checks the result.

## Demo-day fallback

If the venue network or AWS misbehaves, the identical stack runs on the Mac with
`docker compose up -d` — that's the Local Demo Exception the course explicitly allows,
and the browser voice widget still works against `ngrok http 80` if voice is needed.
