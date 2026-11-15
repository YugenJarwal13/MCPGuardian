# Deploying MCP Guardian on AWS (EC2 + Docker Compose)

One EC2 instance runs three containers, started by `docker-compose.yml`:

| Service | Built from | Role | Reachable from the internet |
|---|---|---|---|
| `web` | `frontend/Dockerfile` | the React app and a Caddy reverse proxy for the API and WebSocket | port 80 only |
| `backend` | `backend/Dockerfile` | FastAPI API, CrewAI and ADK inspectors, A2A case manager | no |
| `dvmcp-lab` | `backend/Dockerfile.lab` | the ten DVMCP servers, a sidecar of `backend` (shares its network, listens on 127.0.0.1) | no |

The site is served over **plain HTTP on the instance's Elastic IP** (`http://<elastic-ip>`). No domain is needed or assumed, and no
certificate is requested. Each build context has its own `.dockerignore`. The lab is deliberately vulnerable, so it has no published
port, a read-only filesystem, no Linux capabilities and a memory cap; state lives in Docker named volumes.

Target: AWS, region `ap-south-1` (Mumbai), Ubuntu 24.04 LTS, `c7i-flex.large` (4 GiB, the default), 30 GB encrypted gp3 disk, IMDSv2 required, standard CPU
credits on burstable types, inbound TCP 80 and SSH (only from your machine's IPv4 `/32`), one Elastic IP, nothing else (no load balancer, NAT gateway or Route 53).
Run every `deploy/aws/*.sh` command below from the repository root on your own machine (on Windows, in Git Bash: `cd "/c/Users/<you>/.../MCPGuardian"`).

> **Instance type and the Free plan.** The default is `c7i-flex.large` (2 vCPU, 4 GiB, x86, so the same images). AWS's documentation lists
> `t3.micro`, `t3.small`, `t4g.micro`, `t4g.small`, `c7i-flex.large` and `m7i-flex.large` as Free-plan eligible for accounts created on or
> after 15 July 2025; `t3.medium` is not in that list. Confirm what your account can launch (read-only):
> ```bash
> aws ec2 describe-instance-types --region ap-south-1 --filters Name=free-tier-eligible,Values=true --query 'InstanceTypes[].InstanceType' --output text
> ```
> `c7i-flex.large` is not burstable, so the script skips the CPU-credit setting for it; burstable types (such as `t3.medium`) get standard
> credits. To launch another type, pass it explicitly (`INSTANCE_TYPE=t3.medium`); the script never switches types for you, and an existing
> instance of a different type makes it stop rather than change anything. Two-GiB types such as `t3.small` are likely to run out of memory
> while building the images. Prices and credit rules change; check the AWS pricing page and your Billing console. The script never
> upgrades your account.

## 1. AWS account and IAM authentication
- Use the IAM user created for this deployment (`mcp-guardian-deployer` in account `103973721389`), never the root account. Everything in
  this guide runs in region `ap-south-1` with the default instance type `c7i-flex.large`.
- Its permissions are in **`deploy/aws/iam-policy.json`**: one complete policy for exactly the AWS calls `provision.sh` and `teardown.sh` make.
  - `RunInstances` is limited to `c7i-flex.large` on the instance resource only, with IMDSv2 required; the AMI, root volume, key pair,
    security group, subnet and network interface each have their own statement, without the instance-type condition.
  - Created resources must carry the tags `GuardianDeployment=mcp-guardian` and `Name=mcp-guardian` (tag-on-create only); ingress changes,
    start, Elastic IP association and all teardown actions apply only to resources carrying that tag.
  - Reads are limited to `ap-south-1`; the only SSM access is the Canonical Ubuntu 24.04 image parameter. There is nothing for HTTPS or
    for any other service.
- The policy is about 6,000 characters (AWS counts it without whitespace), under the 6,144 limit for a customer-managed policy, and far over
  the 2,048 limit for an inline *user* policy. Attach it as a **customer-managed policy** (or to a role). An administrator, not the deployer
  user, creates and attaches it, for example:
  ```bash
  aws iam create-policy --policy-name mcp-guardian-deployer --policy-document file://deploy/aws/iam-policy.json
  aws iam attach-user-policy --user-name mcp-guardian-deployer --policy-arn arn:aws:iam::103973721389:policy/mcp-guardian-deployer
  ```
- To launch a different instance type, change the `ec2:InstanceType` value in `deploy/aws/iam-policy.json` first (and pass `INSTANCE_TYPE`).
- Sign in on your own machine so the keys never go into a chat or the repository, using the CLI profile `guardian-login`
  (`aws login --profile guardian-login`). Then `export AWS_PROFILE=guardian-login` (both scripts use that profile by default) and check
  `aws sts get-caller-identity`; the account id it prints is the one you give `teardown.sh` later.
- On Windows, run the scripts in Git Bash. `provision.sh` sets `MSYS_NO_PATHCONV=1` so Git Bash does not rewrite arguments that start
  with `/` (the SSM parameter name and the root device name) before `aws.exe` receives them.

## 2. Create the server with `provision.sh`
```bash
cd "<path to the MCPGuardian repository>"
export AWS_PROFILE=guardian-login
AWS_REGION=ap-south-1 bash deploy/aws/provision.sh                      # default type: c7i-flex.large
# AWS_REGION=ap-south-1 INSTANCE_TYPE=t3.medium bash deploy/aws/provision.sh   # only if your account allows t3.medium
```
Everything it creates is tagged `GuardianDeployment=mcp-guardian` (change the name with `GUARDIAN_NAME`); a re-run finds its resources by
that tag, never by name alone. It creates:
- a security group with exactly two inbound rules: SSH from your current IPv4 `/32` only (kept up to date on a re-run) and TCP 80 from
  anywhere. There is no 443 rule while the deployment is HTTP-only (`ALLOW_HTTPS=yes` adds it, see "HTTPS later");
- an ed25519 key pair saved to `~/.ssh/mcp-guardian.pem` (it refuses to replace an existing key pair or key file);
- an Ubuntu 24.04 instance: encrypted 30 GB gp3 root volume, IMDSv2 required, standard CPU credits (for burstable types);
- an Elastic IP, associated with the instance.

It stops with an explanation, instead of guessing, if it finds more than one tagged resource, a tagged security group with any other
inbound rule, a key pair with the wrong name, an Elastic IP attached elsewhere, or an existing instance that differs from the intended
configuration. At the end it prints the Elastic IP; note it down.

## 3. Connect with SSH
```bash
ssh -i ~/.ssh/mcp-guardian.pem ubuntu@<elastic-ip>
```
On Windows the script restricts the key file with `icacls`; if it warned, run `icacls` on the `.pem` yourself (remove inherited permissions,
grant only your user read) or `ssh` will refuse the key. If SSH is refused after your public IP changed, run `provision.sh` again: it
moves the SSH rule to your new address.

## 4. Check that first-boot setup finished
The instance installs Docker, adds 2 GB of swap and clones the repository on its first boot (about 3 minutes).
```bash
cloud-init status --wait          # "status: done"
ls /var/log/guardian-*            # guardian-base-ready and guardian-setup-complete
docker --version && docker compose version
ls /opt/mcp-guardian
```
`guardian-clone-failed` means the clone failed (private repository, or no network): copy the code to `/opt/mcp-guardian` by hand.

## 5. Configure the production environment
```bash
cd /opt/mcp-guardian
cp deploy/production.env.example deploy/production.env
nano deploy/production.env        # OPENROUTER_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
ln -sf deploy/production.env .env # lets `docker compose` read the optional settings too (.env is git-ignored)
```
Required: `OPENROUTER_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (leave the Langfuse keys empty to run without traces). Never
commit `production.env`. Everything else has a default; `GUARDIAN_SITE_ADDRESS` and `GUARDIAN_PUBLIC_URL` are optional and only matter
once you have a domain (see "HTTPS later").

## 6. Build the images one at a time
Three builds at once can exhaust the memory of the instance, so build sequentially:
```bash
for s in backend dvmcp-lab web; do docker compose build "$s"; done
```
The backend image is the large one (about 2.5 to 3 GB); the first build takes several minutes.
Optionally check the proxy configuration before starting:
```bash
docker run --rm -v "$PWD/frontend/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
```

## 7. Start the stack
```bash
docker compose config --quiet    # validates docker-compose.yml and its variables (prints nothing when fine)
docker compose up -d
docker compose ps                 # backend and dvmcp-lab should become "healthy" (about a minute)
```

## 8. Open the application
`http://<elastic-ip>` in a browser. It is plain HTTP, so the browser shows no padlock; that is expected without a domain.

## 9. Test it
From your own machine (replace `<ip>`):
```bash
curl -s http://<ip>/health                                    # JSON with "ok": true
curl -sI http://<ip>/ | head -1                               # HTTP/1.1 200 OK  (the React app)
curl -s -i -N --max-time 5 http://<ip>/ws/run \
  -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: x3JJHMbDL1EzLkh9GBhXDw==" | head -1
                                                              # HTTP/1.1 101 Switching Protocols  (the WebSocket through Caddy)
curl -s http://<ip>/servers | python3 -c "import sys,json; print(sorted(s['id'] for s in json.load(sys.stdin)['poisoned'] if s.get('live')))"
                                                              # the ten dvmcp-ch1 ... dvmcp-ch10 ids: the lab is reachable by the backend
```
Then in the browser: Live demo (ten attack cards show "running"; run one), Check a server (a public MCP URL), Evaluations. In Langfuse,
a new trace with environment `production` should appear. The lab and backend must not be reachable directly: `curl --max-time 5
http://<ip>:8000/health` and `http://<ip>:9001/sse` should both fail to connect.

## 10. Logs, restarts and updates
In `/opt/mcp-guardian`:
| Task | Command |
|---|---|
| Logs | `docker compose logs -f backend` (also `web`, `dvmcp-lab`) |
| Restart | `docker compose restart backend dvmcp-lab` |
| Memory and CPU | `docker stats --no-stream` |
| Update to the latest code | `git pull && for s in backend dvmcp-lab web; do docker compose build "$s"; done && docker compose up -d` |

State (fingerprints, case history, model-answer cache) lives in the `guardian-state` volume and survives restarts and updates.

## 11. Stopping the application (this is not terminating AWS resources)
```bash
docker compose down               # stops and removes the containers; the named volumes (your data) are kept
```
This stops the application only. **The EC2 instance, its disk and the Elastic IP are still running and still billing.** Stopping the
instance in the console stops compute charges, but the disk and the Elastic IP keep costing; to remove the costs entirely, terminate
the resources (next step). `docker compose down -v` also deletes the volumes (your data).

## 12. Remove everything on AWS with `teardown.sh`
This **terminates** the instance (and its disk) and releases the Elastic IP, security group and key pair; it cannot be undone.
```bash
GUARDIAN_AWS_ACCOUNT=<12-digit account id> AWS_REGION=ap-south-1 bash deploy/aws/teardown.sh
```
It lists exactly what carries the tag `GuardianDeployment=mcp-guardian` (account, region, default VPC, instance, Elastic IP and its
association, security group, key pair and tagged volumes), aborts on duplicates or an Elastic IP attached to something else, and
deletes nothing until you type the confirmation line it prints (deployment name, account and region). Tagged volumes are only reported,
never deleted. The local `.pem` is removed only after the key pair was deleted in AWS.

## HTTPS later (optional, needs a domain you control)
Not part of the first deployment. When you have a domain whose A record points at the Elastic IP, set in `deploy/production.env`:
`GUARDIAN_SITE_ADDRESS=your.domain.example` and `GUARDIAN_PUBLIC_URL=https://your.domain.example`, uncomment the two `443` lines under
`web.ports` in `docker-compose.yml`, run `docker compose up -d`, and open the port from your machine with
`ALLOW_HTTPS=yes AWS_REGION=ap-south-1 INSTANCE_TYPE=<the type you launched> bash deploy/aws/provision.sh` (it adds TCP/UDP 443 to the
security group; the type must match the running instance or the script stops). Caddy then obtains a
certificate automatically.

## Limitations
- **OAuth sign-in** for remote MCP servers (Check a server) needs a callback address the provider accepts. Many providers refuse a plain
  `http://<ip>` callback, so on the HTTP-only deployment use a bearer token, header or query-key credential instead, or set up HTTPS.
- **Traffic is unencrypted** on the HTTP deployment: do not type secrets you care about into the Check-a-server credential fields over it
  from an untrusted network.
- The free model's daily quota (about 50 requests) is shared by every visitor; `GUARDIAN_LLM_RUNS_PER_DAY` caps the site. When it is
  spent, the pages say so and fall back to the regex checks.
- Public mode is on in the image: internal addresses are refused, runs are rate-limited, and the DVMCP challenges that execute commands
  or read files are inspect-only.
- The images have not been built on the target instance yet; the lab's `read_only` filesystem and 512m memory cap are unmeasured on Linux.
  If the lab is killed for memory, raise `mem_limit` for `dvmcp-lab` in `docker-compose.yml`; if a challenge cannot write, check the `/tmp`
  tmpfs first.
