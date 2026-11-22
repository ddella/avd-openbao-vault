# Start Pilot

The commands below can be executed inside the Dev Container, only if you have configured Docker outside of Docker (DooD).

## Step 1: 🚀 Start OpenBao container

Verify that OpenBao is running.

```bash
docker logs -f openbao      # ✅ Check for: "==> OpenBao server started!"
```

If the container is **not** running, start it with:

```bash
docker compose --file /opt/openbao/compose.yaml up --detach
```

## Step 2: 🔓 Unseal OpenBao

### ✔ Check the status

If you just restarted the sever, it is sealed.

```bash
docker exec openbao bao status
```

Output for a sealed database
```text
Key                Value
---                -----
Seal Type          shamir
Initialized        true
Sealed             true 👈
Total Shares       5
Threshold          3
Unseal Progress    0/3
Unseal Nonce       n/a
Version            2.7.3
Commit Date        2026-11-19T20:06:41Z
Storage Type       raft
HA Enabled         true
```

### 🔓 Unseal

Unseal with any 3 of the 5 keys (run 3 times, pasting a different key each time):

```bash
docker exec -it openbao bao operator unseal
```

The unseal keys:

```text
Unseal Key 1: ZTfsbVACt5cAcJbAQRnw1aPUVeNjHVsn0kymPdcPN61d
Unseal Key 2: ojRRaX4/8y5nNRIcFGkrjyqRg2IxWHm/ts2tSE4aQj3N
Unseal Key 3: Mn8RhrF6l4tv/6upZx+IHxFTFOtFJKE+BCc6JpBNpWRb
Unseal Key 4: rG2eYGDD1VWMdw+1sGb9MyO+1UpYjrev1rc5sOjaNVsK
Unseal Key 5: HXrLt10JpC0d+/2riL+jeBj6phey5ttR4dbBA1r6Yy7W
```

### ✔ Check

```bash
docker exec openbao bao status
```

```text
Key                     Value
---                     -----
Seal Type               shamir
Initialized             true
Sealed                  false 👈
```

## Step 3: ⚙️ Set variables

Execute those commands **inside** your Dev Container:

```bash
export VAULT_ADDR=https://openbao.kloud.lan:8200
export VAULT_CACERT="$(realpath bao-cert/openbao.kloud.lan-chain.pem)"
export VAULT_TOKEN="s.yyyyyyyyyyyyyyyyyyyyyyyy"   👈 user token
```

### 🔑 Tokens

Replace the variable `VAULT_TOKEN` with a token below:

| Role | Use token |
|---|---|
| root             | s.zXHWGfCEOA6fnN54C4rpej3n |
| net-prod-dc-all  | s.ygU1IUQvnSvx1ybTnHDsQBHJ |
| net-prod-dc1-dc3 | s.scrmjJak3P4Z5Srg0rXo9wYa |

### 🌐 Web UI

You can access the web user interface via: `https://openbao.kloud.lan:8200/ui`

## Step 4: 🏗️ Build the configuration

Use Arista AVD to build the configuration.

```bash
make build ENV=net-prod           # ❌ Fails with token: net-prod-dc1-dc3
make build DC=DC1 ENV=net-prod    # ✅ Succeed with token: net-prod-dc1-dc3
make build DC=DC2 ENV=net-prod    # ❌ Fails with token: net-prod-dc1-dc3
make build DC=DC3 ENV=net-prod    # ✅ Succeed with token: net-prod-dc1-dc3
```

---

# Rotate a secret

We rotate the DC1 BGP **underlay** password, rebuild, check that only the expected lines changed, then roll back. The full runbook (TACACS, users, deploy precautions) is in [02_openbao-day2-secrets-guide.md](02_openbao-day2-secrets-guide.md) §2.4.

## 1.1 👀 Look at the current config

Open `inventories/net-prod/intended/configs/dc1-leaf1.cfg` and search for `password 7`. Leave the file open; the editor refreshes it after each build.

```bash
grep -n "password 7" inventories/net-prod/intended/configs/dc1-leaf1.cfg
```

```text
190:   neighbor EVPN-OVERLAY-PEERS password 7 cPGjDbabCVIwwkS6qaqgYDHwbDIfG8FSbs4+aFEiGKg=
194:   neighbor IPv4-UNDERLAY-PEERS password 7 jUPfblnPOctD8Ow6dNj7gIYFqpq5F/PrRusuDw3Boj8=   👈 we change this one
```

`intended/` is git-ignored, so `git diff` can't show the change. Keep a copy to compare against:

```bash
rm -rf /tmp/configs-before
cp -r inventories/net-prod/intended/configs /tmp/configs-before
```

## 1.2 🔑 Use a scoped token

You don't need root. The `net-prod-dc1-dc3` token can write DC1 (see [04_Users.md](04_Users.md)):

```bash
export VAULT_TOKEN="s.yyyyyyyyyyyyyyyyyyyyyyyy"   👈 net-prod-dc1-dc3 token from Step 3
bao token lookup -format=json | jq -r '.data.display_name'     # ✅ token-net-prod-dc1-dc3
```

## 1.3 🔢 Find the current version

The mount has `cas_required=true`, so every write must say which version it replaces.

```bash
bao kv metadata get -format=json net-prod/dc/dc1/bgp | jq '.data.current_version'
```

```text
1   👈 use it as -cas below
```

## 1.4 🔄 Rotate the password

Use `patch` (not `put`): it changes `underlay_password` only and keeps `overlay_password` and `mlag_password`. The value is read from the prompt, so it stays out of your shell history.

```bash
printf %s "New DC1 underlay password: "; read -rs V; echo
printf '%s' "$V" | bao kv patch -cas=1 net-prod/dc/dc1/bgp underlay_password=-
unset V
```

```text
====== Metadata ======
Key                Value
---                -----
version            2   👈 new version
```

If the command fails with `check-and-set parameter did not match the current version`, someone wrote in the meantime. Run §1.3 again and retry with the new number.

## 1.5 🏗️ Rebuild DC1 and compare

```bash
make build DC=DC1 ENV=net-prod
diff -r /tmp/configs-before inventories/net-prod/intended/configs
```

Expected: only the `IPv4-UNDERLAY-PEERS password 7` line changes, and only on the four `dc1-*` devices. DC2 and DC3 configs are untouched, and so is the overlay password.

```text
diff -r /tmp/configs-before/dc1-leaf1.cfg inventories/net-prod/intended/configs/dc1-leaf1.cfg
<    neighbor IPv4-UNDERLAY-PEERS password 7 jUPfblnPOctD8Ow6dNj7gIYFqpq5F/PrRusuDw3Boj8=
>    neighbor IPv4-UNDERLAY-PEERS password 7 <new value>
...
```

In production you would now deploy to **all** DC1 devices in the same run (`--limit DC1`), in a maintenance window: underlay BGP sessions stay down until both sides have the new password.

## 1.6 ⏪ Roll back

List the versions, then copy the old one back:

```bash
bao kv metadata get net-prod/dc/dc1/bgp           # all versions with timestamps
bao kv get -version=1 net-prod/dc/dc1/bgp         # check what version 1 contains
bao kv rollback -version=1 net-prod/dc/dc1/bgp    # creates version 3 = copy of version 1
```

A rollback doesn't erase anything: it writes a **new** version (3) with the old content, so the history stays complete. Rebuild and compare again:

```bash
make build DC=DC1 ENV=net-prod
diff -r /tmp/configs-before inventories/net-prod/intended/configs && echo "✅ back to the original"
```

The `password 7` string is generated deterministically from the password, so the configs are byte-identical to the original again.

## 1.7 🚫 Check the scope

The same token can't touch DC2 or the global secrets:

```bash
bao kv patch -cas=1 net-prod/dc/dc2/bgp underlay_password=test   # ❌ permission denied
bao kv patch -cas=1 net-prod/global/aaa test=x                   # ❌ permission denied (read-only)
```

## 1.8 🕵️ Who changed what

If the audit device is enabled ([00_openbao-docker-ubuntu-26.04.md](00_openbao-docker-ubuntu-26.04.md) §10), every request is logged with the identity and the path. Secret values are HMAC'd, never in cleartext:

```bash
docker exec openbao sh -c 'grep "dc/dc1/bgp" /openbao/logs/audit.log | tail -n 5' \
  | jq -r 'select(.type=="response") | [.time, .auth.display_name, .request.operation, .request.path] | @tsv'
```

