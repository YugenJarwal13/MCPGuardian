#!/usr/bin/env bash
# Creates what MCP Guardian needs on AWS with the AWS CLI: a security group, a key pair, one EC2 instance
# (Ubuntu 24.04, encrypted gp3 disk, IMDSv2 only, standard CPU credits) and an Elastic IP.
#
# Safe to re-run. It finds its own resources by the tag GuardianDeployment=<GUARDIAN_NAME> (never by name alone) and
# stops, explaining why, rather than guess, whenever what it finds is not exactly what it would have created:
#   - more than one tagged security group, key pair, instance or Elastic IP;
#   - a tagged security group with any inbound rule other than the four below (it never rewrites foreign rules);
#   - a tagged key pair that is not named GUARDIAN_NAME;
#   - an existing instance whose VPC, type, security group, key pair, tag, IMDSv2 setting, root volume (encrypted, gp3,
#     DISK_GB) or CPU credit mode differ from the intended ones, or cannot be read (it is never modified);
#   - an Elastic IP attached to some other instance.
# Intended inbound rules: TCP 22 from your one IPv4 /32 and TCP 80 from 0.0.0.0/0. Nothing else, no IPv6. (The HTTP-only
# deployment has no use for 443; ALLOW_HTTPS=yes adds TCP/UDP 443 for a later HTTPS setup.)
#
# Run it from the repository root. It uses the AWS CLI profile guardian-login unless AWS_PROFILE says otherwise:
#   export AWS_PROFILE=guardian-login
#   AWS_REGION=ap-south-1 bash deploy/aws/provision.sh                      # default type: c7i-flex.large
#   AWS_REGION=ap-south-1 INSTANCE_TYPE=t3.medium bash deploy/aws/provision.sh   # another type, only if you pass it
# INSTANCE_TYPE must be a type your account and your IAM policy (ec2:InstanceType condition) allow. 4 GiB or more is needed to
# build the images. c7i-flex.large is not burstable, so no CPU-credit setting applies; burstable types get CpuCredits=standard.
#
# Costs money while it exists (instance, disk, Elastic IP): tear it down with deploy/aws/teardown.sh.
set -euo pipefail
export AWS_PROFILE="${AWS_PROFILE:-guardian-login}"      # the verified CLI profile; an AWS_PROFILE you set yourself wins
export MSYS_NO_PATHCONV=1      # Git Bash on Windows would turn "/aws/service/..." and "DeviceName=/dev/sda1" into C:/Program Files/Git/... before aws.exe sees them

REGION="${AWS_REGION:-ap-south-1}"
TYPE="${INSTANCE_TYPE:-c7i-flex.large}"
DISK_GB="${DISK_GB:-30}"
ALLOW_HTTPS="${ALLOW_HTTPS:-no}"                      # yes = also open TCP/UDP 443 (only for a later HTTPS setup)
GUARDIAN_NAME="${GUARDIAN_NAME:-mcp-guardian}"        # not NAME: some shells already set that
TAG_KEY="GuardianDeployment"
KEY_FILE="${KEY_FILE:-$HOME/.ssh/${GUARDIAN_NAME}.pem}"
REPO_URL="${REPO_URL:-https://github.com/YugenJarwal13/MCPGuardian.git}"
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
aws_() { aws --region "$REGION" "$@"; }
fail() { echo "ERROR: $*" >&2; exit 1; }
[[ "$TYPE" =~ ^[a-z0-9-]+\.[a-z0-9-]+$ ]] || fail "INSTANCE_TYPE '$TYPE' does not look like an EC2 instance type (for example c7i-flex.large)."
TAGS="{Key=Name,Value=$GUARDIAN_NAME},{Key=$TAG_KEY,Value=$GUARDIAN_NAME}"
tag_spec() { echo "ResourceType=$1,Tags=[$TAGS]"; }
tagged() { echo "Name=tag:$TAG_KEY,Values=$GUARDIAN_NAME"; }

# pick <label> <command...>: runs the AWS query and sets PICKED to the one id it returns, or "" for none; more than one
# is an error. The query's output is assigned to a variable first, so a failing AWS call stops the script instead of
# reading as "nothing found". (Called directly, not inside $(...), so that fail() ends the script.)
pick() {
  local label="$1" list items=()
  shift
  list="$("$@")"
  read -ra items <<< "$list"
  if [ "${#items[@]}" -gt 0 ] && [ "${items[0]}" = "None" ]; then items=(); fi
  case "${#items[@]}" in
    0) PICKED="" ;;
    1) PICKED="${items[0]}" ;;
    *) fail "more than one $label is tagged $TAG_KEY=$GUARDIAN_NAME: ${items[*]}. Not choosing one for you; resolve this by hand." ;;
  esac
}

# a single IPv4 host address in CIDR form (a.b.c.d/32), not 0.0.0.0
host_cidr() {
  local ip="${1%/32}" o x IFS=.
  [ "$ip/32" = "$1" ] || return 1
  read -ra o <<< "$ip"
  [ "${#o[@]}" -eq 4 ] || return 1
  for x in "${o[@]}"; do
    [[ "$x" =~ ^(0|[1-9][0-9]{0,2})$ ]] && [ "$x" -le 255 ] || return 1
  done
  [ "$ip" != "0.0.0.0" ]
}

# a value AWS actually returned: not empty, and not the "None" the CLI prints or the "null" JMESPath yields for nothing
usable_id() { [ -n "${1:-}" ] && [ "$1" != "None" ] && [ "$1" != "null" ]; }

# burstable (T-family) instance types: the ones that have a CPU credit mode
burstable() { case "$1" in t2.*|t3.*|t3a.*) return 0 ;; esac; return 1; }

# an existing tagged key pair must really be called GUARDIAN_NAME: a matching tag alone proves nothing
require_key_name() {
  [ "$1" = "$GUARDIAN_NAME" ] || fail "the key pair tagged $TAG_KEY=$GUARDIAN_NAME is named '${1:-unknown}', not '$GUARDIAN_NAME'. Not using it; resolve this by hand."
}

# need <what> <actual> <expected>: records a problem in mismatch[] when a fact differs, or cannot be verified at all
need() {
  local what="$1" actual="$2" expected="$3"
  if [ -z "$actual" ] || [ "$actual" = "None" ] || [ "$actual" = "null" ]; then
    mismatch+=("$what could not be verified (AWS returned nothing)")
  elif [ "$actual" != "$expected" ]; then
    mismatch+=("$what is '$actual', expected '$expected'")
  fi
}
# Judges the facts gathered about an existing instance (i_* and v_* variables) against what this script would create.
check_instance() {
  need "VPC" "${i_vpc:-}" "$VPC"
  need "instance type" "${i_type:-}" "$TYPE"
  need "key pair" "${i_key:-}" "$GUARDIAN_NAME"
  need "security groups" "${i_sgs:-}" "$SG"
  need "tag $TAG_KEY" "${i_tag:-}" "$GUARDIAN_NAME"
  need "IMDSv2 (MetadataOptions.HttpTokens)" "${i_tokens:-}" "required"
  need "root device type" "${i_roottype:-}" "ebs"
  need "root volume encryption" "${v_encrypted:-}" "true"
  need "root volume type" "${v_type:-}" "gp3"
  need "root volume size in GiB" "${v_size:-}" "$DISK_GB"
  if burstable "$TYPE"; then need "CPU credit mode" "${i_credit:-}" "standard"; fi
  return 0
}

ACCOUNT="$(aws_ sts get-caller-identity --query Account --output text)"
echo "Profile: $AWS_PROFILE  Account: $ACCOUNT  Region: $REGION  Deployment: $GUARDIAN_NAME  Type: $TYPE"

# --- the one address SSH is allowed from: this machine's public IPv4 address
SSH_CIDR="${SSH_CIDR:-$(curl -4 -fsS https://checkip.amazonaws.com | tr -d '[:space:]')/32}"
host_cidr "$SSH_CIDR" || fail "SSH_CIDR '$SSH_CIDR' is not a single IPv4 address in the form a.b.c.d/32. SSH is never opened to a range. Set SSH_CIDR=<your-ip>/32."

# --- network: the default VPC and our tagged security group
VPC="$(aws_ ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
[ "$VPC" != "None" ] || fail "no default VPC in $REGION; create one or choose another region."
pick "security group" aws_ ec2 describe-security-groups --filters "$(tagged)" "Name=vpc-id,Values=$VPC" --query 'SecurityGroups[].GroupId' --output text
SG="$PICKED"
if [ -z "$SG" ]; then
  other="$(aws_ ec2 describe-security-groups --filters "Name=group-name,Values=$GUARDIAN_NAME" "Name=vpc-id,Values=$VPC" --query 'SecurityGroups[0].GroupId' --output text)"
  [ "$other" = "None" ] || fail "a security group named '$GUARDIAN_NAME' ($other) exists but is not tagged $TAG_KEY=$GUARDIAN_NAME. Not touching it; choose another GUARDIAN_NAME."
  SG="$(aws_ ec2 create-security-group --group-name "$GUARDIAN_NAME" --description "MCP Guardian" --vpc-id "$VPC" \
        --tag-specifications "$(tag_spec security-group)" --query GroupId --output text)"
fi

# Every inbound permission of the group, one line each: protocol;from;to;ipv4 ranges;ipv6 ranges;#group pairs;#prefix lists
sg_rules() {
  aws_ ec2 describe-security-groups --group-ids "$SG" --query \
    "SecurityGroups[0].IpPermissions[].join(';', [IpProtocol, to_string(FromPort), to_string(ToPort), join(',', IpRanges[].CidrIp), join(',', Ipv6Ranges[].CidrIpv6), to_string(length(UserIdGroupPairs)), to_string(length(PrefixListIds))])" \
    --output text | tr '\t' '\n'
}
audit_security_group() {          # refuse to reuse a group that allows anything beyond the intended rules
  local proto from to v4 v6 groups prefixes c ok rules bad=()
  rules="$(sg_rules)"                       # assigned first: if the AWS call fails the script stops, it does not look like "no rules"
  while IFS=';' read -r proto from to v4 v6 groups prefixes; do
    [ -n "$proto" ] || continue
    ok=no
    if [ -n "$v6" ] || [ "$groups" != "0" ] || [ "$prefixes" != "0" ]; then
      ok=no
    elif [ "$proto" = "tcp" ] && [ "$from" = "22" ] && [ "$to" = "22" ]; then
      ok=yes                                              # SSH: single IPv4 hosts only (older ones are replaced below)
      [ -n "$v4" ] || ok=no
      for c in ${v4//,/ }; do host_cidr "$c" || ok=no; done
    elif [ "$v4" = "0.0.0.0/0" ]; then
      case "$proto:$from:$to" in
        tcp:80:80) ok=yes ;;
        tcp:443:443|udp:443:443) if [ "$ALLOW_HTTPS" = yes ]; then ok=yes; fi ;;      # unused unless HTTPS was asked for
      esac
    fi
    [ "$ok" = yes ] || bad+=("protocol=$proto ports=$from-$to ipv4=[$v4] ipv6=[$v6] security-group-sources=$groups prefix-lists=$prefixes")
  done <<< "$rules"
  if [ "${#bad[@]}" -gt 0 ]; then
    echo "ERROR: security group $SG ($GUARDIAN_NAME) has inbound rules that are not part of this deployment:" >&2
    printf '  %s\n' "${bad[@]}" >&2
    fail "Intended rules are only: TCP 22 from one IPv4 /32 and TCP 80 from 0.0.0.0/0 (plus TCP/UDP 443 when ALLOW_HTTPS=yes). Remove the rules above yourself (or use another GUARDIAN_NAME); this script does not rewrite rules it did not create."
  fi
}
audit_security_group

RULES=""
refresh_rules() { RULES="$(sg_rules)"; }           # a variable, so an AWS error stops the script instead of reading as "no rules"
ssh_cidrs() {          # the IPv4 sources currently allowed on TCP 22, one per line
  awk -F';' '$1=="tcp" && $2=="22" && $3=="22" {n=split($4,a,","); for(i=1;i<=n;i++) print a[i]}' <<< "$RULES"
}
has_rule() {           # protocol port cidr
  awk -F';' -v p="$1" -v port="$2" -v c="$3" '$1==p && $2==port && $3==port {n=split($4,a,","); for(i=1;i<=n;i++) if (a[i]==c) found=1} END{exit !found}' <<< "$RULES"
}
allow() {              # protocol port cidr description
  refresh_rules
  if has_rule "$1" "$2" "$3"; then return 0; fi
  aws_ ec2 authorize-security-group-ingress --group-id "$SG" \
    --ip-permissions "IpProtocol=$1,FromPort=$2,ToPort=$2,IpRanges=[{CidrIp=$3,Description=$4}]" >/dev/null
  echo "  added $1/$2 from $3"
}
allow tcp 80  0.0.0.0/0 http
if [ "$ALLOW_HTTPS" = yes ]; then
  allow tcp 443 0.0.0.0/0 https
  allow udp 443 0.0.0.0/0 http3
fi
allow tcp 22  "$SSH_CIDR" ssh-admin                       # the current address goes in first ...
refresh_rules
stale="$(ssh_cidrs)"
for old in $stale; do                                    # ... then older single-address SSH rules go
  [ "$old" = "$SSH_CIDR" ] && continue
  aws_ ec2 revoke-security-group-ingress --group-id "$SG" --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=$old}]" >/dev/null
  echo "  removed old SSH rule for $old"
done

# --- key pair: never replaced, never created under a name that is already taken
pick "key pair" aws_ ec2 describe-key-pairs --filters "$(tagged)" --query 'KeyPairs[].KeyPairId' --output text
if [ -n "$PICKED" ]; then
  key_name="$(aws_ ec2 describe-key-pairs --key-pair-ids "$PICKED" --query 'KeyPairs[0].KeyName' --output text)"
  require_key_name "$key_name"
  [ -f "$KEY_FILE" ] || fail "the key pair '$GUARDIAN_NAME' exists in AWS but the private key is missing at $KEY_FILE. A private key cannot be downloaded again; restore the file, or run teardown.sh and provision again."
else
  taken="$(aws_ ec2 describe-key-pairs --filters "Name=key-name,Values=$GUARDIAN_NAME" --query 'KeyPairs[0].KeyPairId' --output text)"
  [ "$taken" = "None" ] || fail "a key pair named '$GUARDIAN_NAME' exists but is not tagged $TAG_KEY=$GUARDIAN_NAME. Not touching it; choose another GUARDIAN_NAME."
  [ ! -e "$KEY_FILE" ] || fail "$KEY_FILE already exists. Refusing to overwrite it; move it away or choose another KEY_FILE."
  mkdir -p "$(dirname "$KEY_FILE")"
  ( umask 077; aws_ ec2 create-key-pair --key-name "$GUARDIAN_NAME" --key-type ed25519 --tag-specifications "$(tag_spec key-pair)" \
      --query KeyMaterial --output text > "$KEY_FILE" ) || { rm -f "$KEY_FILE"; fail "creating the key pair failed."; }
  chmod 400 "$KEY_FILE"
  if command -v icacls >/dev/null 2>&1 && command -v cygpath >/dev/null 2>&1; then       # Windows: OpenSSH rejects open permissions
    icacls "$(cygpath -w "$KEY_FILE")" /inheritance:r /grant:r "${USERNAME:-$USER}:R" >/dev/null \
      || echo "  WARNING: could not restrict $KEY_FILE; run icacls on it before using ssh."
  fi
  echo "  key pair created; private key saved to $KEY_FILE"
fi

# --- instance
instances() {          # ids of tagged instances in the default VPC that are in the given states
  aws_ ec2 describe-instances --filters "$(tagged)" "Name=vpc-id,Values=$VPC" "Name=instance-state-name,Values=$1" \
    --query 'Reservations[].Instances[].InstanceId' --output text
}
going="$(instances shutting-down)"
if [ -n "$going" ] && [ "$going" != "None" ]; then
  echo "Instance(s) $going are shutting down; waiting for termination before going on."
  # shellcheck disable=SC2086
  aws_ ec2 wait instance-terminated --instance-ids $going
fi
pick "instance" instances pending,running,stopping,stopped
ID="$PICKED"
if [ -n "$ID" ]; then
  # Reuse only an instance that is exactly what this script would have created. Every fact below is read from AWS
  # (the root volume is inspected itself); one that differs, or cannot be read, stops the script. Nothing is modified.
  details="$(aws_ ec2 describe-instances --instance-ids "$ID" --query \
    "Reservations[0].Instances[0].join(';', [to_string(VpcId), to_string(InstanceType), to_string(KeyName), join(',', SecurityGroups[].GroupId), join(',', Tags[?Key=='$TAG_KEY'].Value), to_string(MetadataOptions.HttpTokens), to_string(RootDeviceType), to_string(RootDeviceName)])" --output text)"
  i_vpc="" i_type="" i_key="" i_sgs="" i_tag="" i_tokens="" i_roottype="" i_rootdev="" v_encrypted="" v_type="" v_size="" i_credit=""
  IFS=';' read -r i_vpc i_type i_key i_sgs i_tag i_tokens i_roottype i_rootdev <<< "$details"
  if usable_id "$i_rootdev"; then
    root_vol="$(aws_ ec2 describe-instances --instance-ids "$ID" --query \
      "Reservations[0].Instances[0].BlockDeviceMappings[?DeviceName=='$i_rootdev'].Ebs.VolumeId | [0]" --output text)"
    if usable_id "$root_vol"; then            # empty, None or null: the root volume is unverifiable, so no describe-volumes call
      vol="$(aws_ ec2 describe-volumes --volume-ids "$root_vol" --query \
        "Volumes[0].join(';', [to_string(Encrypted), to_string(VolumeType), to_string(Size)])" --output text)"
      IFS=';' read -r v_encrypted v_type v_size <<< "$vol"
    fi
  fi
  if burstable "$TYPE"; then
    # only the entry whose InstanceId is the instance asked about counts; no entry for it reads as unverifiable
    i_credit="$(aws_ ec2 describe-instance-credit-specifications --instance-ids "$ID" --query \
      "InstanceCreditSpecifications[?InstanceId=='$ID'].CpuCredits | [0]" --output text)"
  fi
  mismatch=()
  check_instance
  if [ "${#mismatch[@]}" -gt 0 ]; then
    printf 'ERROR: instance %s does not match the intended configuration:\n' "$ID" >&2
    printf '  - %s\n' "${mismatch[@]}" >&2
    fail "Not modifying it. Change the settings you passed to match it, or tear the deployment down first."
  fi
  STATE="$(aws_ ec2 describe-instances --instance-ids "$ID" --query 'Reservations[0].Instances[0].State.Name' --output text)"
  if [ "$STATE" = "stopping" ]; then
    echo "Instance $ID is stopping; waiting for it to stop, then starting it."
    aws_ ec2 wait instance-stopped --instance-ids "$ID"
    STATE=stopped
  fi
  if [ "$STATE" = "stopped" ]; then
    echo "Instance $ID is stopped; starting it."
    aws_ ec2 start-instances --instance-ids "$ID" >/dev/null
  else
    echo "Instance $ID is $STATE."
  fi
else
  AMI="$(aws_ ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
         --query Parameter.Value --output text)"
  credit=()
  if burstable "$TYPE"; then credit=(--credit-specification CpuCredits=standard); fi     # no surplus-credit charges
  ID="$(aws_ ec2 run-instances --image-id "$AMI" --instance-type "$TYPE" --key-name "$GUARDIAN_NAME" --security-group-ids "$SG" \
        ${credit[@]+"${credit[@]}"} \
        --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$DISK_GB,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}" \
        --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
        --user-data "$(sed "s#^REPO_URL=.*#REPO_URL=\"$REPO_URL\"#" "$here/cloud-init.sh")" \
        --tag-specifications "$(tag_spec instance)" "$(tag_spec volume)" \
        --query 'Instances[0].InstanceId' --output text)"
fi
aws_ ec2 wait instance-running --instance-ids "$ID"

# --- a fixed public address: only ever one that is free or already ours
pick "Elastic IP" aws_ ec2 describe-addresses --filters "$(tagged)" --query 'Addresses[].AllocationId' --output text
ALLOC="$PICKED"
if [ -z "$ALLOC" ]; then
  ALLOC="$(aws_ ec2 allocate-address --domain vpc --tag-specifications "$(tag_spec elastic-ip)" --query AllocationId --output text)"
else
  current="$(aws_ ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].[InstanceId,AssociationId]' --output text)"
  read -r attached_to association <<< "$current"
  if [ "$attached_to" = "$ID" ]; then
    ALLOC_DONE=yes
  elif [ "$attached_to" != "None" ] || [ "$association" != "None" ]; then
    fail "Elastic IP $ALLOC is already associated with '$attached_to' (association $association), not with instance $ID. Not taking it; release or move it yourself."
  fi
fi
[ "${ALLOC_DONE:-no}" = yes ] || aws_ ec2 associate-address --instance-id "$ID" --allocation-id "$ALLOC" >/dev/null
IP="$(aws_ ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].PublicIp' --output text)"

cat <<MSG

Instance $ID is running at $IP (first-boot setup takes about 3 minutes).
  1. ssh -i "$KEY_FILE" ubuntu@$IP
  2. check the first-boot result: ls /var/log/guardian-*   (guardian-setup-complete = Docker, swap and the code are in place)
  3. then follow docs/deployment.md, step 5. The site will be at http://$IP (no domain needed).
MSG
