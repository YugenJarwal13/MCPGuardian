# Deploying MCP Guardian on AWS (EC2 + Docker Compose)

Three containers on one EC2 instance, started by `docker-compose.yml`:

| Service | Image built from | Role | Published |
|---|---|---|---|
| `web` | `frontend/Dockerfile` | the React app, HTTPS (Caddy, automatic certificate), proxy for the API and WebSocket | ports 80, 443 |
| `backend` | `backend/Dockerfile` | FastAPI API, CrewAI and ADK inspectors, A2A case manager | none |
| `dvmcp-lab` | `backend/Dockerfile.lab` | the ten DVMCP servers, a sidecar of `backend` (shares its network, listens on 127.0.0.1) | none |

Each build context has its own `.dockerignore`. The lab is deliberately vulnerable, so it has no published port, a read-only
filesystem, no Linux capabilities and a memory cap. Only `web` is reachable from the internet.

## 1. AWS account and access
- Use an IAM user (never the root account) with programmatic access, or an SSO profile. Needed permissions:
  - to provision: `ec2:DescribeVpcs`, `ec2:DescribeSecurityGroups`, `ec2:CreateSecurityGroup`, `ec2:AuthorizeSecurityGroupIngress`,
    `ec2:RevokeSecurityGroupIngress`, `ec2:DescribeKeyPairs`, `ec2:CreateKeyPair`, `ec2:DescribeInstances`, `ec2:RunInstances`,
    `ec2:StartInstances`, `ec2:DescribeAddresses`, `ec2:AllocateAddress`, `ec2:AssociateAddress`, `ec2:CreateTags`,
    `ec2:DescribeVolumes`, `ec2:DescribeInstanceCreditSpecifications`, and
    `ssm:GetParameter` on the Canonical Ubuntu image parameter;
  - to tear down: `ec2:TerminateInstances`, `ec2:ReleaseAddress`, `ec2:DeleteSecurityGroup`, `ec2:DeleteKeyPair`, `ec2:DescribeVolumes`
    (and the describe permissions above).
- Configure it on your machine, so the keys never go into a chat or the repo: `aws configure --profile guardian`, then
  `export AWS_PROFILE=guardian` and check `aws sts get-caller-identity`.
- Pick a region near your visitors (default `ap-south-1`, Mumbai).

## 2. Create the server
```bash
AWS_REGION=ap-south-1 INSTANCE_TYPE=t3.medium bash deploy/aws/provision.sh
```
Every resource it creates is tagged `GuardianDeployment=mcp-guardian` (change the name with `GUARDIAN_NAME`), and re-running finds them
by that tag, never by name alone. It stops, with an explanation, instead of guessing when it finds more than one tagged resource, a
tagged security group with any inbound rule other than the four intended ones (it shows the rules and does not rewrite them), an
existing instance that differs in VPC, type, security group, key pair, tag, IMDSv2, root-volume encryption, type (gp3) or size, or CPU credit mode, or an Elastic IP attached to another instance. SSH must be
one IPv4 address (`SSH_CIDR`, detected by default); a range is refused. It creates a security group (SSH from your current IP only, kept up to date on a re-run; 80 and 443 open),
an ed25519 key pair saved to `~/.ssh/mcp-guardian.pem` (it stops with an error rather than replace a key pair or a key file that already
exists), an Ubuntu 24.04 instance (standard CPU credits, encrypted 30 GB disk, IMDSv2 only; a stopped instance is started), and an
Elastic IP. On Windows the script restricts the key file with `icacls`; if that warns, restrict it yourself before using `ssh`. A first-boot
script installs Docker, adds 2 GB of swap and clones the repository to `/opt/mcp-guardian`; `ls /var/log/guardian-*` on the server
shows `guardian-setup-complete` when all of that worked, or `guardian-clone-failed` if the clone did not. (If the repository is private,
set `REPO_URL` to a URL with a read-only token, or copy the code by `scp`.)

Size: the stack needs about 1 GB at rest, and building the images needs more, so use `t3.medium` (4 GB, the default); `t3.small` (2 GB)
is likely to run out of memory during the build. Check current prices on the AWS pricing page: an instance, its disk and the Elastic IP are
billed while they exist.

## 3. DNS
Create an A record for the domain (`careeristpro.cloud`) and for `www` pointing at the Elastic IP, in whichever DNS service holds the
domain (Route 53 or the registrar). Check with `nslookup careeristpro.cloud`. Caddy cannot get a certificate until this resolves.

## 4. Configure and start
```bash
ssh -i ~/.ssh/mcp-guardian.pem ubuntu@<elastic-ip>
cd /opt/mcp-guardian
cp deploy/production.env.example deploy/production.env
nano deploy/production.env       # OPENROUTER_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
ln -sf deploy/production.env .env                    # every later `docker compose` command reads the same settings (`.env` is git-ignored)
# build one image at a time: three builds at once can exhaust the memory of a small instance
for s in backend dvmcp-lab web; do docker compose build "$s"; done
docker compose up -d
docker compose ps                # backend and dvmcp-lab should become "healthy"
```

## 5. Check
- `https://careeristpro.cloud/health` returns JSON with `"ok": true`.
- Live demo: the ten DVMCP cards show "running"; run one.
- Check a server: run it on a public MCP URL; for an OAuth server, approve on the provider's page.
- Langfuse shows a new trace with environment `production`.

## Operations
| Task | Command (in `/opt/mcp-guardian`) |
|---|---|
| Update | `git pull && for s in backend dvmcp-lab web; do docker compose build "$s"; done && docker compose up -d` |
| Logs | `docker compose logs -f backend` (also `web`, `dvmcp-lab`) |
| Restart | `docker compose restart backend dvmcp-lab` |
| Memory use | `docker stats --no-stream` |
| Stop | `docker compose down` (volumes, with the history and certificates, are kept) |
| Remove everything on AWS | `GUARDIAN_AWS_ACCOUNT=<account id> bash deploy/aws/teardown.sh`: lists the tagged resources, aborts on duplicates or an Elastic IP attached elsewhere, and deletes nothing until you type the confirmation line (name, account and region). Detached volumes are reported, never deleted. |

State (fingerprints, case history, model-answer cache) lives in the `guardian-state` volume and the certificates in `caddy-data`.
Take a snapshot of the instance's disk if you want a backup.

## Notes
- The free model's daily quota (about 50 requests) is shared by every visitor; `GUARDIAN_LLM_RUNS_PER_DAY` caps the site.
- Public mode is on in the image: internal addresses are refused, runs are rate-limited, and the DVMCP challenges that execute
  commands or read files are inspect-only.
- OAuth sign-in needs `GUARDIAN_PUBLIC_URL`; compose sets it to `https://$GUARDIAN_DOMAIN`.
- Not verified yet: the three images have not been built (Docker is not installed on the development machine), so the first build
  on the server is the first real test. Likeliest issue: if the lab's read-only filesystem blocks a challenge, remove
  `read_only: true` from `dvmcp-lab` in `docker-compose.yml`.
