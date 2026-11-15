#!/usr/bin/env bash
# Removes what provision.sh created, and only that: resources that carry the tag GuardianDeployment=<GUARDIAN_NAME>, in
# the given region and (where the resource type has a VPC) the default VPC. Nothing untagged, nothing matched by name.
#
#   export AWS_PROFILE=guardian
#   GUARDIAN_AWS_ACCOUNT=<12-digit account id> AWS_REGION=ap-south-1 bash deploy/aws/teardown.sh
#
# GUARDIAN_AWS_ACCOUNT is required and must equal the account you are signed in to. The script lists everything it found,
# refuses to go on if the picture is ambiguous (duplicates, an Elastic IP attached to something else), and deletes
# nothing until you type the confirmation line it prints. Detached volumes are reported, never deleted.
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
GUARDIAN_NAME="${GUARDIAN_NAME:-mcp-guardian}"        # not NAME: some shells already set that
TAG_KEY="GuardianDeployment"
KEY_FILE="${KEY_FILE:-$HOME/.ssh/${GUARDIAN_NAME}.pem}"
aws_() { aws --region "$REGION" "$@"; }
fail() { echo "ERROR: $*" >&2; exit 1; }
tagged() { echo "Name=tag:$TAG_KEY,Values=$GUARDIAN_NAME"; }

# one_of <label> <command...>: runs the AWS query and sets PICKED to the single id it returns ("" for none); more than
# one is ambiguous, so we stop. The output is assigned to a variable first, so a failing AWS call stops the script
# instead of reading as "nothing found".
one_of() {
  local label="$1" list items=()
  shift
  list="$("$@")"
  read -ra items <<< "$list"
  if [ "${#items[@]}" -gt 0 ] && [ "${items[0]}" = "None" ]; then items=(); fi
  case "${#items[@]}" in
    0) PICKED="" ;;
    1) PICKED="${items[0]}" ;;
    *) fail "more than one $label is tagged $TAG_KEY=$GUARDIAN_NAME: ${items[*]}. Ambiguous, so nothing was deleted. Resolve this by hand." ;;
  esac
}

# provision.sh creates exactly one instance, so more than one tagged instance is unexpected and is never terminated here
refuse_multiple_instances() {          # <instance ids separated by spaces>
  local ids=()
  read -ra ids <<< "${1:-}"
  if [ "${#ids[@]}" -gt 1 ]; then
    echo "ERROR: ${#ids[@]} instances carry the tag $TAG_KEY=$GUARDIAN_NAME, but this deployment has exactly one:" >&2
    printf '  %s\n' "${ids[@]}" >&2
    fail "Manual investigation is required (another deployment? a leftover?). Nothing was terminated or deleted."
  fi
}

# --- the account must be named explicitly and match the credentials in use
[ -n "${GUARDIAN_AWS_ACCOUNT:-}" ] || fail "set GUARDIAN_AWS_ACCOUNT to the 12-digit id of the account this deployment lives in."
[[ "$GUARDIAN_AWS_ACCOUNT" =~ ^[0-9]{12}$ ]] || fail "GUARDIAN_AWS_ACCOUNT must be a 12-digit account id."
ACCOUNT="$(aws_ sts get-caller-identity --query Account --output text)"
[ "$ACCOUNT" = "$GUARDIAN_AWS_ACCOUNT" ] || fail "signed in to account $ACCOUNT, but GUARDIAN_AWS_ACCOUNT is $GUARDIAN_AWS_ACCOUNT. Nothing was touched."
VPC="$(aws_ ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"
[ "$VPC" != "None" ] || fail "no default VPC in $REGION."

# --- find everything first (read-only)
IDS="$(aws_ ec2 describe-instances --filters "$(tagged)" "Name=vpc-id,Values=$VPC" \
       "Name=instance-state-name,Values=pending,running,shutting-down,stopping,stopped" --query 'Reservations[].Instances[].InstanceId' --output text)"
[ "$IDS" != "None" ] || IDS=""
IDS="${IDS//$'\t'/ }"                                  # the CLI separates ids with tabs; the checks below use spaces
refuse_multiple_instances "$IDS"
one_of "Elastic IP" aws_ ec2 describe-addresses --filters "$(tagged)" --query 'Addresses[].AllocationId' --output text
ALLOC="$PICKED"
one_of "security group" aws_ ec2 describe-security-groups --filters "$(tagged)" "Name=vpc-id,Values=$VPC" --query 'SecurityGroups[].GroupId' --output text
SG="$PICKED"
one_of "key pair" aws_ ec2 describe-key-pairs --filters "$(tagged)" --query 'KeyPairs[].KeyPairId' --output text
KEY_ID="$PICKED"
VOLUMES="$(aws_ ec2 describe-volumes --filters "$(tagged)" --query "Volumes[].[VolumeId,State,join(',',Attachments[].InstanceId)]" --output text)"

# --- an Elastic IP is released only if it is free or attached to one of our own instances
ASSOC="not associated"
if [ -n "$ALLOC" ]; then
  current="$(aws_ ec2 describe-addresses --allocation-ids "$ALLOC" --query 'Addresses[0].[InstanceId,AssociationId]' --output text)"
  read -r attached_to association <<< "$current"
  if [ "$attached_to" != "None" ]; then
    case " $IDS " in
      *" $attached_to "*) ASSOC="associated with $attached_to (in the list below)" ;;
      *) fail "Elastic IP $ALLOC is associated with $attached_to, which is not one of this deployment's instances (${IDS:-none}). Nothing was deleted." ;;
    esac
  elif [ "$association" != "None" ]; then
    fail "Elastic IP $ALLOC has association $association that is not an instance of this deployment. Nothing was deleted."
  fi
fi

# --- show it all
echo "Account:          $ACCOUNT"
echo "Region:           $REGION"
echo "Default VPC:      $VPC"
echo "Deployment:       $GUARDIAN_NAME  (tag $TAG_KEY=$GUARDIAN_NAME)"
echo "Instances:        ${IDS:-none}"
echo "Elastic IP:       ${ALLOC:-none}${ALLOC:+  ($ASSOC)}"
echo "Security group:   ${SG:-none}"
echo "Key pair:         ${KEY_ID:-none}"
echo "Tagged volumes (reported, never deleted by this script):"
if [ -n "$VOLUMES" ] && [ "$VOLUMES" != "None" ]; then echo "$VOLUMES" | sed 's/^/  /'; else echo "  none"; fi
if [ -z "$IDS$ALLOC$SG$KEY_ID" ]; then echo "Nothing to remove."; exit 0; fi

CONFIRM="delete $GUARDIAN_NAME account $ACCOUNT region $REGION"
echo
read -r -p "To delete exactly the resources above, type: $CONFIRM
> " typed
[ "$typed" = "$CONFIRM" ] || { echo "Cancelled. Nothing was deleted."; exit 1; }

# --- delete, by id
if [ -n "$IDS" ]; then
  # shellcheck disable=SC2086
  aws_ ec2 terminate-instances --instance-ids $IDS >/dev/null
  # shellcheck disable=SC2086
  aws_ ec2 wait instance-terminated --instance-ids $IDS
fi
[ -z "$ALLOC" ] || aws_ ec2 release-address --allocation-id "$ALLOC"
status=0
if [ -n "$SG" ]; then
  deleted=no
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do          # a terminated instance's network interface can take a moment to go
    if aws_ ec2 delete-security-group --group-id "$SG" 2>/dev/null; then deleted=yes; break; fi
    sleep 5
  done
  [ "$deleted" = yes ] || { echo "WARNING: could not delete security group $SG (still in use?). Delete it later." >&2; status=1; }
fi
if [ -n "$KEY_ID" ]; then
  aws_ ec2 delete-key-pair --key-pair-id "$KEY_ID"
  # the local private key goes only after the tagged key pair was deleted in AWS
  if [ -e "$KEY_FILE" ]; then rm -f "$KEY_FILE" && echo "Removed local private key $KEY_FILE"; fi
fi

# --- what is left
left="$(aws_ ec2 describe-volumes --filters "$(tagged)" --query 'Volumes[].[VolumeId,State]' --output text)"
if [ -n "$left" ] && [ "$left" != "None" ]; then
  echo "Tagged volumes still present (not deleted; check them in the console and delete if you no longer need them):"
  echo "$left" | sed 's/^/  /'
fi
echo "Done."
exit "$status"
