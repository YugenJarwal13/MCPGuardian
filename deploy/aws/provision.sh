#!/usr/bin/env bash
# Creates what MCP Guardian needs on AWS with the AWS CLI: a security group, a key pair, one EC2 instance
# (Ubuntu 24.04, encrypted gp3 disk, IMDSv2 only) and an Elastic IP. Safe to re-run: existing pieces are reused.
#
#   export AWS_PROFILE=guardian            # a profile created with `aws configure --profile guardian`
#   AWS_REGION=ap-south-1 INSTANCE_TYPE=t3.small bash deploy/aws/provision.sh
#
# Costs money while it exists (instance, disk, Elastic IP): tear it down with deploy/aws/teardown.sh.
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
TYPE="${INSTANCE_TYPE:-t3.small}"
DISK_GB="${DISK_GB:-30}"
NAME="${NAME:-mcp-guardian}"
KEY_FILE="${KEY_FILE:-$HOME/.ssh/${NAME}.pem}"
REPO_URL="${REPO_URL:-https://github.com/YugenJarwal13/MCPGuardian.git}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
aws_() { aws --region "$REGION" "$@"; }

echo "Account: $(aws_ sts get-caller-identity --query Account --output text)  Region: $REGION  Type: $TYPE"
MYIP="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"

# --- network: the default VPC, a security group (SSH from this machine only; web from anywhere)
VPC="$(aws_ ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
[ "$VPC" != "None" ] || { echo "No default VPC in $REGION; create one or pass a different region."; exit 1; }
SG="$(aws_ ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" "Name=vpc-id,Values=$VPC" --query 'SecurityGroups[0].GroupId' --output text)"
if [ "$SG" = "None" ]; then
  SG="$(aws_ ec2 create-security-group --group-name "$NAME" --description "MCP Guardian" --vpc-id "$VPC" --query GroupId --output text)"
  aws_ ec2 authorize-security-group-ingress --group-id "$SG" --ip-permissions \
    "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$MYIP/32,Description=ssh from the admin machine}]" \
    "IpProtocol=tcp,FromPort=80,ToPort=80,IpRanges=[{CidrIp=0.0.0.0/0}]" \
    "IpProtocol=tcp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]" \
    "IpProtocol=udp,FromPort=443,ToPort=443,IpRanges=[{CidrIp=0.0.0.0/0}]" >/dev/null
fi

# --- key pair (the private key is written once, here, and never printed)
if ! aws_ ec2 describe-key-pairs --key-names "$NAME" >/dev/null 2>&1; then
  mkdir -p "$(dirname "$KEY_FILE")"
  aws_ ec2 create-key-pair --key-name "$NAME" --key-type ed25519 --query KeyMaterial --output text > "$KEY_FILE"
  chmod 400 "$KEY_FILE"
fi

# --- instance
ID="$(aws_ ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" Name=instance-state-name,Values=pending,running,stopped \
      --query 'Reservations[0].Instances[0].InstanceId' --output text)"
if [ "$ID" = "None" ]; then
  AMI="$(aws_ ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
         --query Parameter.Value --output text)"
  ID="$(aws_ ec2 run-instances --image-id "$AMI" --instance-type "$TYPE" --key-name "$NAME" --security-group-ids "$SG" \
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}" \
        --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
        --user-data "$(sed "s#^REPO_URL=.*#REPO_URL=\"$REPO_URL\"#" "$here/cloud-init.sh")" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" "ResourceType=volume,Tags=[{Key=Name,Value=$NAME}]" \
        --query 'Instances[0].InstanceId' --output text)"
fi
aws_ ec2 wait instance-running --instance-ids "$ID"

# --- a fixed public address
IP="$(aws_ ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].PublicIp' --output text)"
if [ "$IP" = "None" ]; then
  ALLOC="$(aws_ ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)"
  aws_ ec2 associate-address --instance-id "$ID" --allocation-id "$ALLOC" >/dev/null
  IP="$(aws_ ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)"
fi

cat <<MSG

Instance $ID is running at $IP (first-boot setup takes about 3 minutes).
  1. DNS: point an A record for your domain (and www) at $IP.
  2. ssh -i "$KEY_FILE" ubuntu@$IP
  3. then follow docs/deployment.md, step 3.
MSG
