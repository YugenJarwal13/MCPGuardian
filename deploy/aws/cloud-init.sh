#!/bin/bash
# EC2 user data (runs once as root on first boot): Docker, swap, and the code. The keys are added afterwards by hand.
# Status markers (check with `ls /var/log/guardian-*`):
#   guardian-base-ready      Docker and swap are installed
#   guardian-setup-complete  the code was cloned too: nothing else is needed before step 4 of docs/deployment.md
#   guardian-clone-failed    the clone failed (private repository? no network?): copy the code to /opt/mcp-guardian by hand
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
REPO_URL="${REPO_URL:-https://github.com/YugenJarwal13/MCPGuardian.git}"

apt-get update
apt-get -y install ca-certificates curl git
curl -fsSL https://get.docker.com | sh                       # Docker Engine + the compose plugin
usermod -aG docker ubuntu
systemctl enable --now docker

# 2 GB of swap: a safety margin on a small instance (the stack itself needs about 1 GB)
if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
touch /var/log/guardian-base-ready

if git clone "$REPO_URL" /opt/mcp-guardian; then
  chown -R ubuntu:ubuntu /opt/mcp-guardian
  touch /var/log/guardian-setup-complete
else
  echo "git clone of $REPO_URL failed (private repository?): copy the code to /opt/mcp-guardian by hand" >&2
  touch /var/log/guardian-clone-failed
  exit 1                                                     # so `cloud-init status` reports the failure
fi
