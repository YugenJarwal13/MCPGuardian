#!/usr/bin/env bash
# Removes everything provision.sh created (instance, disk, Elastic IP, security group, key pair). Asks first.
set -euo pipefail
REGION="${AWS_REGION:-ap-south-1}"; NAME="${NAME:-mcp-guardian}"; KEY_FILE="${KEY_FILE:-$HOME/.ssh/${NAME}.pem}"
aws_() { aws --region "$REGION" "$@"; }
read -r -p "Delete the '$NAME' instance, Elastic IP, security group and key pair in $REGION? Type yes: " ok
[ "$ok" = "yes" ] || { echo "Cancelled."; exit 1; }
ID="$(aws_ ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" Name=instance-state-name,Values=pending,running,stopped --query 'Reservations[0].Instances[0].InstanceId' --output text)"
if [ "$ID" != "None" ]; then aws_ ec2 terminate-instances --instance-ids "$ID" >/dev/null; aws_ ec2 wait instance-terminated --instance-ids "$ID"; fi
ALLOC="$(aws_ ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].AllocationId' --output text)"
[ "$ALLOC" = "None" ] || aws_ ec2 release-address --allocation-id "$ALLOC"
SG="$(aws_ ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" --query 'SecurityGroups[0].GroupId' --output text)"
[ "$SG" = "None" ] || aws_ ec2 delete-security-group --group-id "$SG"
aws_ ec2 delete-key-pair --key-name "$NAME" 2>/dev/null || true
rm -f "$KEY_FILE"
echo "Removed."
