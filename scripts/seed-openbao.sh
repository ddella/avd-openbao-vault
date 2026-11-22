#!/usr/bin/env bash
# Seed OpenBao mounts and read-only AppRoles used by global_vars/secret.yml.
# Requires: bao CLI, BAO_ADDR and an admin BAO_TOKEN.
set -euo pipefail

# AppRole auth is shared; each role receives access only to its environment mount.
bao auth enable approle 2>/dev/null || true

for ENV in net-prod net-staging net-lab; do
  bao secrets enable -path="$ENV" kv-v2 2>/dev/null || true

  read -rsp "$ENV TACACS server1 key: " TACKEY; echo
  bao kv put -mount="$ENV" global/aaa tacacs_server1_key="$TACKEY"

  for DC in dc1 dc2 dc3; do
    read -rsp "$ENV $DC BGP underlay password: " UNDERLAY; echo
    read -rsp "$ENV $DC BGP overlay password:  " OVERLAY; echo
    bao kv put -mount="$ENV" "dc/$DC/bgp" underlay_password="$UNDERLAY" overlay_password="$OVERLAY"
  done

  POLICY="avd-${ENV}-readonly"
  ROLE="avd-${ENV}"
  bao policy write "$POLICY" - <<EOF
path "$ENV/data/*" {
  capabilities = ["read"]
}
EOF

  bao write "auth/approle/role/$ROLE" token_policies="$POLICY" token_ttl=30m token_max_ttl=1h
  echo "$ENV role_id:"
  bao read -field=role_id "auth/approle/role/$ROLE/role-id"
  echo "$ENV secret_id:"
  bao write -f -field=secret_id "auth/approle/role/$ROLE/secret-id"
done
