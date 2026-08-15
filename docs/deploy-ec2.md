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
- **Security group**: inbound `22` (SSH, your IP only), plus `80` and `443`
  (HTTP/HTTPS, anywhere)

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

## 5. Add HTTPS to the EC2 public IP

ElevenLabs requires a trusted HTTPS custom-LLM endpoint. Let’s Encrypt now issues
short-lived certificates directly for public IP addresses, so a domain is optional.

Add these values to the server's `.env`:

```dotenv
PUBLIC_HOST=EC2_PUBLIC_IP
LETSENCRYPT_EMAIL=you@example.com
```

Then provision the first certificate and start the HTTPS Compose overlay:

```bash
./scripts/provision-ip-https.sh
curl -I https://EC2_PUBLIC_IP/
```

IP certificates last about six days. Install a daily renewal cron job on the EC2 host:

```bash
(crontab -l 2>/dev/null; echo '17 3 * * * cd /home/ubuntu/voice-agent && ./scripts/renew-ip-https.sh >> /home/ubuntu/voice-agent/certbot-renew.log 2>&1') | crontab -
```

For later deploys, keep using the overlay:

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

## 6. Point ElevenLabs at it

In the agent's dashboard settings, set the custom LLM Server URL to:

```
https://EC2_PUBLIC_IP/api/agent/v1
```

Set the custom LLM API key to the same value as `ELEVENLABS_LLM_API_KEY` in
the server's `.env`. Add both `localhost` and the EC2 IP to the agent's allowed origins.

## Updating after a code change

Manual way, on the box:

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
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
| Secret | `EC2_SECURITY_GROUP_ID` | the instance's security group (`sg-…`) |
| Secret | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION` | an IAM user allowed only to authorize/revoke ingress on that one group |

Why the AWS credentials: the security group keeps SSH restricted to your own IP, and
GitHub's runners come from a different address every time. So the deploy job opens port
22 for the runner's IP, deploys, and closes it again in an `always()` step. The IAM user
holds exactly those two permissions on exactly that group and nothing else.

From then on, `git push` is the deployment: CI proves the stack, then the deploy job
SSHes in, resets the box to `origin/main`, rebuilds, and health-checks the result.

## Demo-day fallback

If the venue network or AWS misbehaves, the identical stack runs on the Mac with
`docker compose up -d` — that's the Local Demo Exception the course explicitly allows,
and the browser voice widget still works against `ngrok http 80` if voice is needed.
