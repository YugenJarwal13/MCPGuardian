#!/bin/bash
# EC2 user data (runs once as root on first boot): Docker, swap, and the code. The keys are added afterwards by hand.
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

git clone "$REPO_URL" /opt/mcp-guardian || true
chown -R ubuntu:ubuntu /opt/mcp-guardian
touch /var/log/cloud-init-guardian.done
