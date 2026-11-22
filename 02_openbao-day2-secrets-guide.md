# OpenBao Day 2 guide: structuring and managing AVD secrets across data centers and environments

This guide covers two things:

1. **Structure:** how to lay out OpenBao (mounts, paths, policies) and the AVD repo for several data centers, each with several environments.
2. **Day 2 runbooks:** adding, changing, rotating, rolling back and deleting secrets safely.

Everything below was tested against OpenBao (KV v2) and AVD 6.5.

---

## Part 1: Structure

### 1.1 Design principles

| Principle | Why |
|---|---|
| **One KV mount per environment** (`net-prod`, `net-staging`, `net-lab`) | A hard boundary between environments. Policies, audit, version limits and CI credentials are set per mount, so a lab token can never read prod. |
| **Inside a mount, use `global/` and `dc/<dc>/`** | Secrets shared across the environment live once in `global/`. Per-site secrets live under `dc/<dc>/`. |
| **One secret per category, many keys inside** | `dc/dc1/bgp` holds `underlay_password` and `overlay_password`. One lookup fetches both, and they're versioned together. |
| **Lowercase, stable names that match the inventory** | `bao_dc: dc1` in the inventory maps directly to `dc/dc1/...`. |
| **Never copy prod secrets into lower environments** | Each environment has its own values. |

### 1.2 Path layout

```
net-prod/                          ← KV v2 mount (one per environment)
├── global/
│   ├── aaa           TACACS, RADIUS, and enable credentials
│   ├── users         local-user passwords/hashes and SSH keys
│   ├── eapi          eAPI username and password
│   ├── snmp          SNMPv2 communities and SNMPv3 auth/priv keys
│   ├── security      MACsec, IPsec, and NTP authentication keys
│   ├── cvp           CloudVision credentials and tokens
│   ├── syslog        syslog TLS key
│   └── certificates  HTTPS private key and related material
└── dc/
    ├── dc1/
    │   └── bgp       underlay, overlay, MLAG, and EVPN route-server passwords
    ├── dc2/
    │   └── bgp       same keys, independent values
    └── dc3/
        └── bgp       same keys, independent values

net-staging/                       ← same tree, different values
net-lab/                           ← same tree, different values
```

`global/` means shared by every DC **inside that environment**; it does not mean shared between prod, staging, and lab. Keep independent values in each mount. `dc/<dc>/bgp` holds that DC's `underlay_password`, `overlay_password`, `mlag_password`, and `evpn_route_server_password`, supplied by `datacenters.<dc>.bgp` in `bao-secrets-template.yml`.

**Is a secret global or per DC?** Scope it by its rotation and ownership boundary. TACACS, users, and SNMP are shared across DCs within an environment; BGP passwords are per DC so a site can be rotated independently. The other template categories above are shown under `global/` as environment-wide values; move a value under `dc/<dc>/` if it is actually site-specific.

**Alternative:** a single `network/` mount with `<env>/<dc>/...` paths also works. You lose the per-mount boundary, though, and a policy mistake like `network/data/*` then exposes every environment. Mount per environment is the safer default.

### 1.3 Create the mounts (once per environment)

The secrets engines must be configured in advance before they can perform their functions. These steps are usually completed by an operator or configuration management tool.

```bash
declare -a environments=("prod" "staging" "lab")

for env in "${environments[@]}"; do
  bao secrets enable -path=net-$env -description="Network secrets for ($env)" kv-v2
  bao write net-$env/config max_versions=10 cas_required=true
done
```

- **`max_versions=10`** keeps the last 10 versions of each secret for rollback.
- **`cas_required=true`** forces check-and-set on every write, so two people (or a script) can't silently overwrite each other's changes. 

### Verification

```bash
bao secrets list
```

### 1.4 AVD repository layout

Use one inventory per environment and a shared `global_vars/secret.yml`:

```
avd-fabric/
├── ansible.cfg
├── ansible-vault-template.yml     ← schema/reference; placeholders only
├── bao-secrets-template.yml       ← one-environment Bao import bundle
├── playbooks/
│   ├── build.yml
│   └── deploy.yml
├── global_vars/
│   └── secret.yml                 ← shared lookup logic, no values
└── inventories/
    ├── net-prod/
    │   ├── inventory.yml          ← sets bao_env: net-prod
    │   └── group_vars/
    │       ├── FABRIC.yml         ← wires secrets into AVD keys
    │       ├── DC1.yml            ← sets bao_dc: dc1 + topology
    │       ├── DC2.yml            ← sets bao_dc: dc2
    │       └── DC3.yml            ← sets bao_dc: dc3
    ├── net-staging/
    │   └── ...
    └── net-lab/
        └── ...
```

Use `bao-secrets-template.yml` as the human-readable input bundle, with one populated copy per environment. It reshapes the example in `ansible-vault-template.yml` into `global` and `datacenters` sections. `scripts/import-bao-secrets.py` maps `global.<category>` to `<environment>/global/<category>` and `datacenters.<dc>.<category>` to `<environment>/dc/<dc>/<category>`, omitting null fields and empty categories.

The OpenBao paths map to these bundle sections:

| OpenBao path | Template fields |
|---|---|
| `global/aaa` | `global.aaa` (TACACS, RADIUS, enable) |
| `global/users` | `global.users` |
| `global/eapi` | `global.eapi` |
| `global/snmp` | `global.snmp` (SNMPv2 and SNMPv3) |
| `global/security` | `global.security` (MACsec, IPsec, NTP) |
| `global/cvp` | `global.cvp` |
| `global/syslog` | `global.syslog` |
| `global/certificates` | `global.certificates` |
| `dc/dc1/bgp` | `datacenters.dc1.bgp` |
| `dc/dc2/bgp` | `datacenters.dc2.bgp` |
| `dc/dc3/bgp` | `datacenters.dc3.bgp` |

Set `environment` to `net-prod`, `net-staging`, or `net-lab` in each copy. The template uses `null` for unfilled values; replace them with customer-provided values, and do not commit a populated copy. With Bao CLI authentication configured through its environment, review planned paths and import with:

```bash
python3 scripts/import-bao-secrets.py .secrets/bao-secrets-net-prod.yml --dry-run
python3 scripts/import-bao-secrets.py .secrets/bao-secrets-net-prod.yml
```

The importer creates missing paths and recursively merges non-null values into existing categories, preserving fields not present in the input. It uses CAS on every write and skips categories that are already up to date. Lists are replaced as a whole; `null` values are ignored and do not delete stored fields. The importer policy therefore needs `create`, `read`, and `update` on that environment's `data/*` paths. Use `--overwrite` only for intentional full-category replacement: omitted fields are removed. The current `global_vars/secret.yml` demonstrates lookups for `global/aaa` and `dc/<dc>/bgp`; add lookups for the other categories when they are wired into AVD.

#### `ansible.cfg`

```ini
[defaults]
# No default inventory on purpose: always pass -i inventories/net-<env>/inventory.yml
host_key_checking = False
vars_plugins_enabled = arista.avd.global_vars, host_group_vars

[vars_global_vars]
# Relative to the inventory file (inventories/net-<env>/inventory.yml)
paths = ../../global_vars
```

#### `inventories/net-prod/inventory.yml`

```yaml
---
all:
  vars:
    bao_env: net-prod              # selects the OpenBao mount
  children:
    FABRIC:
      children:
        DC1:
          children:
            DC1_SPINES:
              hosts:
                dc1-spine1:
                dc1-spine2:
            DC1_L3_LEAVES:
              hosts:
                dc1-leaf1:
                dc1-leaf2:
        DC2:
          children:
            DC2_SPINES:
              hosts:
                dc2-spine1:
                dc2-spine2:
            DC2_L3_LEAVES:
              hosts:
                dc2-leaf1:
                dc2-leaf2:
        DC3:
          children:
            DC3_SPINES:
              hosts:
                dc3-spine1:
                dc3-spine2:
            DC3_L3_LEAVES:
              hosts:
                dc3-leaf1:
                dc3-leaf2:
```

#### `inventories/net-prod/group_vars/DC1.yml` (top of the file)

```yaml
---
bao_dc: dc1                        # selects <environment>/dc/dc1/*
# ... spine / l3leaf topology as usual ...
```

#### `global_vars/secret.yml`

```yaml
---
# Path convention:
#   <environment>/global/<category>    shared by all DCs in that environment
#   <environment>/dc/<dc>/<category>   DC-specific
# bao_env is set per inventory; bao_dc per DC group.
bao_mount: "{{ bao_env }}"

# One lookup per OpenBao secret (returns all its keys)
_bao_global_aaa: "{{ lookup('community.hashi_vault.vault_kv2_get', 'global/aaa', engine_mount_point=bao_mount).secret }}"
_bao_dc_bgp: "{{ lookup('community.hashi_vault.vault_kv2_get', 'dc/' ~ bao_dc ~ '/bgp', engine_mount_point=bao_mount).secret }}"

# Friendly names used by group_vars
bgp:
  underlay:
    password: "{{ _bao_dc_bgp.underlay_password }}"
  overlay:
    password: "{{ _bao_dc_bgp.overlay_password }}"

aaa:
  tacacs:
    server1:
      key: "{{ _bao_global_aaa.tacacs_server1_key }}"
```

`inventories/net-prod/group_vars/FABRIC.yml` wires the resolved secrets into AVD (`cleartext_password`, `cleartext_key`, and so on). It doesn't need to know about DC-specific paths.

#### Build and deploy

```bash
make build ENV=net-lab
make build ENV=net-staging
make build ENV=net-prod
ansible-playbook -i inventories/net-prod/inventory.yml playbooks/deploy.yml --limit DC1
```

Each environment writes its own `inventories/net-<env>/intended/` and `inventories/net-<env>/documentation/` (keep both git-ignored). Builds are deterministic: if no secret or input changed, the configs are byte-identical, so deploys only change what really changed.

### 1.5 Policies

Create separate policies for each environment and identity. The examples below use `net-prod`; repeat them with `net-staging` or `net-lab` in the policy name and mount path. KV v2 policies use API paths: `data/` for secret values and `metadata/` for listing and metadata operations, even though `bao kv` commands omit those segments.

**AVD build read access.** The pipeline only needs to read secret values:

```hcl
# avd-prod-read
path "net-prod/data/*" { capabilities = ["read"] }
```

**YAML importer access.** The importer reads existing data, recursively merges supplied fields, and writes with the current version as CAS. New paths use `-cas=0`. Give its environment-specific token only the capabilities needed for those operations:

```hcl
# bao-prod-import
path "net-prod/data/*" { capabilities = ["create", "read", "update"] }
```

`--overwrite` uses the same policy but replaces the full category payload instead of merging. Missing fields are removed, so reserve it for intentional replacement.

**Secret maintenance access.** This example lets operators read and write values, list paths, soft-delete and restore versions, and patch custom metadata. It does not grant permanent destruction:

```hcl
# netops-prod-write
path "net-prod/data/*"       { capabilities = ["create", "read", "update", "patch"] }
path "net-prod/metadata/*"   { capabilities = ["read", "list", "patch"] }
path "net-prod/delete/*"     { capabilities = ["update"] }
path "net-prod/undelete/*"   { capabilities = ["update"] }
```

`list` belongs on `metadata/`, not `data/`. Keep `update` on `destroy/*` and `delete` on `metadata/*` out of routine policies; those allow permanent version destruction or removal of the entire secret and its metadata.

**Optional, per-DC delegation**, for example a site team that only manages DC2:

```hcl
# netops-prod-dc2-write
path "net-prod/data/dc/dc2/*"       { capabilities = ["create", "read", "update", "patch"] }
path "net-prod/metadata/dc/dc2/*"   { capabilities = ["read", "list", "patch"] }
path "net-prod/delete/dc/dc2/*"     { capabilities = ["update"] }
path "net-prod/undelete/dc/dc2/*"   { capabilities = ["update"] }
```

An administrator (or a dedicated policy administrator) must write these policies and attach them to the intended token/AppRole. A secret-import token cannot grant itself access by writing a policy. These commands install policy definitions; they do not create mounts or attach policies to tokens.

> ‼️ **Check the mount first.** The above policy files target `net-prod/`. Do not apply them until `net-prod/` exists. The per-environment design in this guide expects a separate mount for each environment.

Use only the policies needed for your workflow: `bao-net-prod-import` for the YAML importer, `avd-net-prod-read` for AVD builds, and `netops-net-prod-write` for authorized human maintenance. Apply them using an identity authorized to manage ACL policies:

```bash
bao policy write avd-net-prod-read - < policies/avd-net-prod-read.hcl
bao policy write bao-net-prod-import - < policies/bao-net-prod-import.hcl
bao policy write netops-net-prod-write - < policies/netops-net-prod-write.hcl
```

> [!NOTE] You can add `docker exec -i openbao` before each command to execute it inside the container.  

Keep the `.hcl` files in Git (in a separate repo, or a `policies/` folder) so policy changes go through review.

### 1.6 Pipeline credentials: one AppRole per environment

```bash
bao auth enable approle        # once

bao write auth/approle/role/avd-net-prod \
    token_policies=avd-net-prod-read \
    token_ttl=20m token_max_ttl=1h \
    secret_id_ttl=90d \
    secret_id_bound_cidrs="10.0.10.0/24"   # your CI runners (optional)

# bao write auth/approle/role/avd-lab \
#     token_policies=avd-lab-read token_ttl=1h
```

In CI, set `ANSIBLE_HASHI_VAULT_AUTH_METHOD=approle`, `ANSIBLE_HASHI_VAULT_ROLE_ID` and `ANSIBLE_HASHI_VAULT_SECRET_ID`, using the role that matches the target environment. A lab pipeline physically can't read prod.

People use their own logins (`userpass` or OIDC) mapped to the `netops-<env>-write` policies.

AppRole is for **CI builds**, not for importing secrets:

- `bao auth enable approle` enables the AppRole login method once for the OpenBao server.
- `bao write auth/approle/role/...` creates a machine identity. `token_policies` assigns the permissions that identity receives after login.
- The TTL settings limit the token’s lifetime. `secret_id_bound_cidrs` is optional; replace the example CIDR with your CI runner’s address range if you use it.
- CI uses the generated Role ID and Secret ID to log in. Keep the Secret ID in your CI’s secret store, not in the repo.

The read policy is appropriate for CI builds; use the separate `bao-net-prod-import` policy for the importer, not the CI AppRole.

---

## Part 2: Day 2 runbooks

All commands assume:

```bash
export VAULT_ADDR=https://openbao.kloud.lan:8200
export BAO_ADDR="$VAULT_ADDR"

export CERT_PATH="$(realpath bao-cert/openbao.kloud.lan-chain.pem)"
export VAULT_CACERT="$CERT_PATH"
export BAO_CACERT="$CERT_PATH"

make build ENV=net-prod
```

### 2.1 Key concepts

| Command | What it does | Watch out |
|---|---|---|
| `bao kv put` | Writes a **new version containing only the keys you give** | ⚠️ Any key you leave out is **removed** from the new version |
| `bao kv patch` | Writes a new version, **merging** your keys into the current ones | Fails (404) if the latest version is deleted |
| `-cas=N` | Write only if the current version is `N` (`-cas=0` means "only if it doesn't exist yet") | Required on every write because of `cas_required=true` |
| `bao kv rollback -version=N` | Copies version N into a **new** latest version | History is kept |
| `bao kv delete` | Soft-deletes the latest version (recoverable) | AVD builds fail until you undelete it |
| `bao kv destroy -versions=N` | Permanently erases version N | Admin only |

**Rule of thumb:** use `patch` to change values, and `put -cas=0` only to create.

**Keep secrets out of shell history.** Pass `key=-` and pipe the value in:

```bash
printf %s "New value: "; read -rs V; echo
printf '%s' "$V" | bao kv patch -cas=<ver> net-prod/dc/dc1/bgp underlay_password=-
unset V
```

(Only one key per command can use `-`.)

### 2.2 Find the current version (needed for `-cas`)

```bash
bao kv metadata get -format=json net-prod/dc/dc1/bgp | jq '.data.current_version'
```

If someone else wrote in the meantime, your write fails with `check-and-set parameter did not match the current version`. Re-read the version and the value, then retry.

### 2.3 Add a new secret

#### YAML template workflow

Use the environment file under `.secrets/` as the source of truth:

1. Choose the scope: put values shared by all DCs in `global.<category>`; put site-specific values in `datacenters.<dc>.<category>`.
2. Add the field to `.secrets/bao-secrets-net-prod.yml`. For example, NTP keys belong at `global.security.ntp.auth_keys.key1` and `key2`.
3. Preview target paths, then import: `python3 scripts/import-bao-secrets.py .secrets/bao-secrets-net-prod.yml --dry-run`, followed by the same command without `--dry-run`.
4. Add a lookup in `global_vars/secret.yml` that matches the nested field shape, then reference it from the AVD variable that consumes the secret.
5. Build the environment, for example `make build ENV=net-prod`.

The importer recursively merges non-null values into existing categories, preserving fields not present in the input. It uses CAS on every write and skips categories that are already up to date. Lists are replaced as a whole; `null` values are ignored and do not delete stored fields. The importer policy therefore needs `create`, `read`, and `update` on that environment's `data/*` paths. Use `--overwrite` only for intentional full-category replacement: omitted fields are removed.

The shared NTP configuration is in `group_vars/ntp.yml`. `playbooks/build.yml` explicitly loads this file because the inventories and their `group_vars` are nested under `inventories/<environment>/`. NTP `hash_algorithm` (currently `md5`) is configuration, not a secret. Because NTP is enabled in the shared build config, add/import the key values under `global.security.ntp.auth_keys` in every environment before building that environment.

**Case A: a new key in an existing category** (e.g. a second TACACS server):

```bash
bao kv patch -cas=<ver> net-prod/global/aaa tacacs_server2_key=-     # value via stdin
```

Repeat for every environment (`net-staging`, `net-lab`) with that environment's own value. Then reference it in `global_vars/secret.yml`:

```yaml
aaa:
  tacacs:
    server2:
      key: "{{ _bao_global_aaa.tacacs_server2_key }}"
```

Then use `aaa.tacacs.server2.key` in `group_vars`.

**Case B: a new category** (e.g. SNMPv3):

```bash
printf %s "SNMP auth: "; read -rs A; echo
printf '%s' "$A" | bao kv put   -cas=0 net-prod/global/snmp v3_auth=-   # create (v1)
printf %s "SNMP priv: "; read -rs P; echo
printf '%s' "$P" | bao kv patch -cas=1 net-prod/global/snmp v3_priv=-   # add 2nd key (v2)
unset A P
```

Then add a lookup in `secret.yml`:

```yaml
_bao_global_snmp: "{{ lookup('community.hashi_vault.vault_kv2_get', 'global/snmp', engine_mount_point=bao_mount).secret }}"
snmp:
  v3:
    auth: "{{ _bao_global_snmp.v3_auth }}"
    priv: "{{ _bao_global_snmp.v3_priv }}"
```

> **Order matters:** create the secret in **every** environment's mount **before** merging the `secret.yml` change. Otherwise builds for the missing environment fail.

### 2.4 Change or rotate a secret

General flow:

1. `bao kv patch -cas=<ver> ...` the new value.
2. Build: `make build ENV=net-<env>`.
3. Review the diff of `intended/configs` (only the expected lines should change).
4. Deploy in a change window, scoped with `--limit`.
5. Verify, or roll back (§2.5).

**BGP passwords (per DC).** A password mismatch keeps the session down. Changing it on one side drops the session until the peer has the same value. To limit impact:
- Rotate one DC at a time (that's why BGP is stored per DC).
- Deploy to all devices of that DC in the same run: `--limit DC1`. Spines and leaves of the DC share the peer groups.
- Expect underlay and overlay sessions in that DC to flap briefly. Do it in a maintenance window.
- To keep impact smaller, rotate `underlay_password` and `overlay_password` in separate changes.

**TACACS keys (global).** Change the key on the TACACS server first, if it supports several keys per client. Otherwise change both together. Make sure local fallback (`aaa authentication login default group TACACS local`) and a local admin account work before you start, so a mismatch doesn't lock you out.

**Local user hashes.** Store hashes (`sha512`), not cleartext passwords. Generate one on an EOS device or with `openssl passwd -6`, then patch it in.

### 2.5 History and rollback

```bash
bao kv metadata get net-prod/dc/dc1/bgp          # all versions with timestamps
bao kv get -version=3 net-prod/dc/dc1/bgp        # read an older version
bao kv rollback -version=3 net-prod/dc/dc1/bgp   # make v3 the new latest
```

Then rebuild and redeploy. A rollback is just another new version, so the full history is kept.

**Who changed what:** the audit log (`/openbao/logs/audit.log`) records every request with the authenticated identity and path. Secret values in it are HMAC'd, not stored in cleartext.

### 2.6 Delete, undelete, destroy

```bash
bao kv delete   net-prod/dc/dc3/bgp                 # soft-delete latest version
bao kv undelete -versions=<N> net-prod/dc/dc3/bgp   # restore it
bao kv destroy  -versions=<N> net-prod/dc/dc3/bgp   # permanent (admin)
bao kv metadata delete net-prod/dc/dc3/bgp          # wipe all versions + metadata (admin)
```

> A soft-deleted secret looks **missing** to AVD lookups and to `kv patch` (404). Undelete it before patching or building.

### 2.7 Add a new data center

1. **Create its secrets** in each environment where the DC exists:
   ```bash
  printf %s "Underlay: "; read -rs U; echo; printf '%s' "$U" | bao kv put   -cas=0 net-prod/dc/dc4/bgp underlay_password=-
  printf %s "Overlay:  "; read -rs O; echo; printf '%s' "$O" | bao kv patch -cas=1 net-prod/dc/dc4/bgp overlay_password=-
   unset U O
   ```
2. **Add the inventory groups** `DC4`, `DC4_SPINES` and `DC4_L3_LEAVES`, with `bao_dc: dc4` in `group_vars/DC4.yml` for each environment that will host it.
3. **Optional:** add a per-DC write policy for the site team.
4. Build and check that `dc3-*` configs have their own password strings.

### 2.8 Add a new environment

1. Create the mount (`net-<env>`) with `max_versions` and `cas_required` (§1.3).
2. Create its `global/*` and `dc/<dc>/*` secrets with **new** values.
3. Write the `avd-<env>-read` and `netops-<env>-write` policies and an `avd-<env>` AppRole.
4. Copy an inventory folder to `inventories/net-<env>/` and set `bao_env: net-<env>`.

### 2.9 Document each secret (custom metadata)

```bash
bao kv metadata patch \
  -custom-metadata=owner=netops \
  -custom-metadata=rotation=90d \
  -custom-metadata=used_by=avd-bgp \
  net-prod/dc/dc1/bgp
```

This is visible with `bao kv metadata get`. It's useful for rotation reviews.

### 2.10 Inventory of what exists

```bash
bao kv list net-prod/global
bao kv list net-prod/dc
bao kv list net-prod/dc/dc1
```

For a full tree per environment:

```bash
mount=net-prod
for c in $(bao kv list -format=json "$mount/global" | jq -r '.[]'); do echo "global/$c"; done
for dc in $(bao kv list -format=json "$mount/dc" | jq -r '.[]'); do
  for c in $(bao kv list -format=json "$mount/dc/$dc" | jq -r '.[]'); do echo "dc/$dc$c"; done
done
```

### 2.11 Before bulk changes: snapshot

```bash
docker exec openbao bao operator raft snapshot save /tmp/pre-change.snap
docker cp openbao:/tmp/pre-change.snap ./backup/pre-change-$(date +%F-%H%M).snap
```

---

## Part 3: Troubleshooting

| Symptom during `playbooks/build.yml` / `bao` | Cause | Fix |
|---|---|---|
| `check-and-set parameter required` | `cas_required=true` on the mount | Add `-cas=<current_version>` (or `-cas=0` to create) |
| `check-and-set parameter did not match` | Someone wrote since you read | Re-read the version and value, retry |
| `kv patch` returns 404 | Secret missing, or latest version soft-deleted | `kv metadata get` to check, then `kv undelete` |
| A key "disappeared" after an update | Used `kv put` instead of `kv patch` | `kv rollback -version=<previous>`, then use `patch` |
| Lookup error mentioning `dc/<x>/bgp` | Secret not created for that DC/environment, or `bao_dc` typo | Create the secret, or fix `group_vars/<DC>.yml` |
| `'dict object' has no attribute 'xyz'` | Key missing inside the secret | `kv patch` the key into that environment |
| `permission denied` | Token/AppRole for the wrong environment, or policy too narrow | Use the matching `avd-<env>` role, check with `bao token capabilities net-<env>/data/<path>` |
| `bao_env is undefined` | Missing `all.vars.bao_env` in the inventory | Add it to `inventories/net-<env>/inventory.yml` |
