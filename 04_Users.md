# Scoped tokens for `net-prod`

Your admin token (root or `daniel`) can do everything. For daily work, hand out tokens that can only reach the part of the tree they need.

| Token | Read/write | Read only |
|---|---|---|
| **dc-all** | `net-prod/dc/*` (DC1, DC2, DC3 and any future DC) | `net-prod/global/*` |
| **dc1-dc3** | `net-prod/dc/dc1/*`, `net-prod/dc/dc3/*` | `net-prod/global/*` |

Everything else is denied, including `net-prod/dc/dc2/*` for the dc1-dc3 token and every other mount (`net-staging`, `net-lab`, `sys/`, ...).

> [!NOTE] Every command below runs **inside the Dev Container**. Set `VAULT_ADDR`, `VAULT_CACERT` and your admin `VAULT_TOKEN` first (see [01_openbao_unseal.md](01_openbao_unseal.md)). To run a command in the server container instead, add `docker exec -i openbao` before it.

---

## 1. How it works

A token doesn't hold permissions itself. It carries a list of **policies**, and each policy grants **capabilities** on **paths**. A request is allowed only if one of the token's policies allows it; anything not listed is denied.

```
token ──► policies ──► path rules ──► allow / deny
```

We build each token from two policies:

```
dc-all token   = net-prod-global-read + netops-net-prod-dc-all-write
dc1-dc3 token  = net-prod-global-read + netops-net-prod-dc1-dc3-write
```

The `net-prod-global-read` policy is shared, so "all tokens can read `global/*`" is defined in one place.

### KV v2 paths in policies

`net-prod` is a KV v2 mount. The CLI hides it, but the API (and therefore policies) puts an extra segment after the mount name:

| What you type | What the policy must match |
|---|---|
| `bao kv get net-prod/global/aaa` | `net-prod/data/global/aaa` |
| `bao kv put` / `bao kv patch` | `net-prod/data/...` |
| `bao kv list net-prod/dc/` | `net-prod/metadata/dc/` (with `list`) |
| `bao kv metadata get ...` | `net-prod/metadata/...` |
| `bao kv delete` / `bao kv undelete` | `net-prod/delete/...`, `net-prod/undelete/...` |

So a policy rule written as `path "net-prod/global/*"` matches **nothing**. Always include `data/` or `metadata/`.

### Glob matching

- `*` is only allowed **at the end** and matches anything, including more `/` levels. `net-prod/data/dc/*` matches `dc/dc1/bgp`, `dc/dc2/bgp`, `dc/dc9/anything/deep`.
- A path without `*` matches **exactly** that path. `net-prod/metadata/dc/` lets you list the DC names and nothing deeper.

---

## 2. The policies

The files are in [policies/](policies/).

### 2.1 Shared: read `global/*`

[policies/net-prod-global-read.hcl](policies/net-prod-global-read.hcl)

```hcl
# Read-only access to environment-wide secrets. Attach to every net-prod token.
path "net-prod/data/global/*"      { capabilities = ["read"] }
path "net-prod/metadata/global/*"  { capabilities = ["read", "list"] }

# Navigation only: list the top of the mount (shows "global/" and "dc/" names, no values)
path "net-prod/metadata/"          { capabilities = ["list"] }
```

No `create`, `update` or `patch`, so a holder can't change TACACS, SNMP or user secrets.

### 2.2 All data centers: read/write `dc/*`

[policies/netops-net-prod-dc-all-write.hcl](policies/netops-net-prod-dc-all-write.hcl)

```hcl
path "net-prod/data/dc/*"       { capabilities = ["create", "read", "update", "patch"] }
path "net-prod/metadata/dc/*"   { capabilities = ["read", "list", "patch"] }
path "net-prod/delete/dc/*"     { capabilities = ["update"] }
path "net-prod/undelete/dc/*"   { capabilities = ["update"] }

path "net-prod/metadata/dc/"    { capabilities = ["list"] }
```

A new DC (`dc/dc4/...`) is covered automatically.

### 2.3 DC1 and DC3 only

[policies/netops-net-prod-dc1-dc3-write.hcl](policies/netops-net-prod-dc1-dc3-write.hcl)

```hcl
path "net-prod/data/dc/dc1/*"       { capabilities = ["create", "read", "update", "patch"] }
path "net-prod/metadata/dc/dc1/*"   { capabilities = ["read", "list", "patch"] }
path "net-prod/delete/dc/dc1/*"     { capabilities = ["update"] }
path "net-prod/undelete/dc/dc1/*"   { capabilities = ["update"] }

path "net-prod/data/dc/dc3/*"       { capabilities = ["create", "read", "update", "patch"] }
path "net-prod/metadata/dc/dc3/*"   { capabilities = ["read", "list", "patch"] }
path "net-prod/delete/dc/dc3/*"     { capabilities = ["update"] }
path "net-prod/undelete/dc/dc3/*"   { capabilities = ["update"] }

path "net-prod/metadata/dc/"        { capabilities = ["list"] }
```

`dc2` is never named, so it's denied. Listing `net-prod/dc/` still shows the name `dc2/`, but not its secrets. Remove the last rule if even the names must stay hidden; the user then has to type the full path (`net-prod/dc/dc1/...`) instead of browsing in the UI.

### Why these capabilities

| Capability | Path | Allows |
|---|---|---|
| `read` | `data/` | Read the current or an older version |
| `create`, `update` | `data/` | Write a new secret or a new version (`bao kv put -cas=N`) |
| `patch` | `data/` | Change some keys only (`bao kv patch`) |
| `list` | `metadata/` | Browse paths (`bao kv list`, UI tree) |
| `read`, `patch` | `metadata/` | See versions, edit custom metadata |
| `update` | `delete/`, `undelete/` | Soft-delete and restore a version |

Deliberately **not** granted: `destroy/*` (permanent wipe of a version) and `delete` on `metadata/*` (removes the secret and all its history). Keep those for the admin.

> [!TIP] Need a **read-only** DC token instead (for example a CI build)? Keep only the `read` lines on `data/` and `read`, `list` on `metadata/`.

### 2.4 Install the policies

```bash
cd /workspaces/avd-openbao-vault

bao policy write net-prod-global-read          - < policies/net-prod-global-read.hcl
bao policy write netops-net-prod-dc-all-write  - < policies/netops-net-prod-dc-all-write.hcl
bao policy write netops-net-prod-dc1-dc3-write - < policies/netops-net-prod-dc1-dc3-write.hcl

bao policy list
```

Run the same `bao policy write` again whenever you edit a file. The change applies immediately to every existing token that carries the policy; you don't need to create new tokens.

---

## 3. Create the tokens

### 3.1 Why use token roles

A token created with a plain `bao token create` is a **child** of the token that created it. If your admin token expires or is revoked (your `userpass` login token does expire), all its children are revoked with it.

A **token role** fixes that: it creates **orphan** tokens (no parent), limits which policies they may get, and sets their lifetime. Create the roles once:

```bash
bao write auth/token/roles/net-prod-dc-all \
    allowed_policies="net-prod-global-read,netops-net-prod-dc-all-write" \
    orphan=true \
    renewable=true \
    token_ttl=720h \
    token_max_ttl=2160h

bao write auth/token/roles/net-prod-dc1-dc3 \
    allowed_policies="net-prod-global-read,netops-net-prod-dc1-dc3-write" \
    orphan=true \
    renewable=true \
    token_ttl=720h \
    token_max_ttl=2160h
```

| Setting | Meaning |
|---|---|
| `allowed_policies` | The only policies a token from this role can have. Asking for another one fails. |
| `orphan=true` | The token survives when your admin token expires. |
| `token_ttl=720h` | Valid for 30 days, unless renewed. |
| `token_max_ttl=2160h` | Hard limit of 90 days, even with renewals. After that, issue a new token. |

### 3.2 Issue the tokens

```bash
bao token create -role=net-prod-dc-all \
    -policy=net-prod-global-read -policy=netops-net-prod-dc-all-write \
    -display-name=net-prod-dc-all
```

Example output for `net-prod-dc-all`:

```text
token                s.ygU1IUQvnSvx1ybTnHDsQBHJ      👈 give this to the user
token_accessor       7KWMrMO7ZiRRLO8wnT6Bct6D        👈 keep this to manage the token
token_duration       768h
token_renewable      true
token_policies       ["default" "net-prod-global-read" "netops-net-prod-dc-all-write"]
identity_policies    []
policies             ["default" "net-prod-global-read" "netops-net-prod-dc-all-write"]
```

```bash
bao token create -role=net-prod-dc1-dc3 \
    -policy=net-prod-global-read -policy=netops-net-prod-dc1-dc3-write \
    -display-name=net-prod-dc1-dc3
```

Example output for `net-prod-dc1-dc3`:

```text
Key                  Value
---                  -----
token                s.scrmjJak3P4Z5Srg0rXo9wYa      👈 give this to the user
token_accessor       gJP3NbJ72lxM9icDBSTkEJTO        👈 keep this to manage the token
token_duration       768h
token_renewable      true
token_policies       ["default" "net-prod-global-read" "netops-net-prod-dc1-dc3-write"]
identity_policies    []
policies             ["default" "net-prod-global-read" "netops-net-prod-dc1-dc3-write"]
```

- **`token`** is the secret. Send it through a password manager, never by email, chat or Git.
- **`token_accessor`** lets you look up, renew or revoke the token without knowing the secret. Record it with the owner's name.
- The `default` policy is added automatically. It only lets a token look up, renew and revoke **itself**.

---

## 4. Verify

### 4.1 Check capabilities without using the token

As admin, ask OpenBao what a token may do on a path:

```bash
DC13="s.scrmjJak3P4Z5Srg0rXo9wYa"      # the dc1-dc3 token

bao token capabilities $DC13 net-prod/data/global/aaa    # read
bao token capabilities $DC13 net-prod/data/dc/dc1/bgp    # create, patch, read, update
bao token capabilities $DC13 net-prod/data/dc/dc3/bgp    # create, patch, read, update
bao token capabilities $DC13 net-prod/data/dc/dc2/bgp    # deny
bao token capabilities $DC13 net-staging/data/global/aaa # deny
```

### 4.2 Try it as the user

Open a new shell and use only the scoped token:

```bash
export VAULT_TOKEN="s.scrmjJak3P4Z5Srg0rXo9wYa"      # the dc1-dc3 token

bao kv get net-prod/global/aaa         # ✅ works
bao kv get net-prod/dc/dc1/bgp         # ✅ works
bao kv get net-prod/dc/dc2/bgp         # ❌ permission denied
bao kv patch -cas=0 net-prod/global/aaa test=x   # ❌ permission denied (global is read-only)
bao kv list net-prod/dc/               # ✅ dc1/ dc2/ dc3/ (names only)
```

The same token works in the web UI: `https://openbao.kloud.lan:8200/ui`, method **Token**.

> [!NOTE] The mount uses `cas_required=true`, so every write needs `-cas`. Use `-cas=0` for a new secret, or the current version number to update an existing one (see [02_openbao-day2-secrets-guide.md](02_openbao-day2-secrets-guide.md)).

---

### 4.3 Try with `make build ...`

```bash
make build DC=DC1 ENV=net-prod
```

[playbooks/build.yml](playbooks/build.yml) reads `dc/<dc>/bgp` only for the DCs of the hosts in the `--limit`, and prints them:

```text
TASK [🖨 Print DCs fetched from OpenBao]
ok: [dc1-spine1] =>
    msg: 'Fetching dc/<dc>/* secrets for: dc1'
```

Hosts of other DCs get a `NOT-FETCHED-outside-limit` placeholder instead of an OpenBao call. AVD still loads their variables to compute fabric-wide facts, but writes no config for them, so the placeholder never appears in `intended/configs`.

What the dc1-dc3 token can build:

| Command | Result |
|---|---|
| `make build ENV=net-prod DC=DC1` | ✅ |
| `make build ENV=net-prod DC=DC3` | ✅ |
| `ansible-playbook -i inventories/net-prod/inventory.yml -e ENV=net-prod --limit DC1,DC3 playbooks/build.yml` | ✅ |
| `make build ENV=net-prod DC=DC2` | ❌ `403 permission denied` on `net-prod/data/dc/dc2/bgp` |
| `make build ENV=net-prod` (all DCs) | ❌ same, because DC2 is in the run |

> 💪 The two failures are intended: the token isn't allowed to read DC2's secrets.

---

## 5. Manage the tokens

All of these run as admin, using the accessor:

```bash
bao list auth/token/accessors                          # all token accessors
bao token lookup  -accessor YYYYYYYYYYYYYYYYYYYYYYYY   # owner, policies, expiry
bao token renew   -accessor YYYYYYYYYYYYYYYYYYYYYYYY   # extend by token_ttl (up to max)
bao token revoke  -accessor YYYYYYYYYYYYYYYYYYYYYYYY   # kill it now
```

The user can also renew their own token before it expires:

```bash
bao token renew      # uses VAULT_TOKEN
bao token lookup     # shows ttl and policies
```

| Task | What to do |
|---|---|
| Someone leaves, or a token leaks | `bao token revoke -accessor ...` |
| Give dc1-dc3 access to DC2 as well | Edit `netops-net-prod-dc1-dc3-write.hcl`, run `bao policy write` again. Existing tokens pick up the change. |
| A token reached its 90-day max TTL | Issue a new one with `bao token create -role=...` |
| Same access for `net-staging` / `net-lab` | Copy the three policies, replace `net-prod` with the environment name, create matching roles. |

---

## 6. Tokens or user logins?

Tokens are quick to set up, but a token is a shared secret with no name behind it. For people, prefer a personal login that carries the same policies, so the audit log shows who did what and the user picks their own password:

```bash
read -rsp "Password for alice: " P; echo
printf '%s' "$P" | bao write auth/userpass/users/alice \
    password=- \
    token_policies="net-prod-global-read,netops-net-prod-dc1-dc3-write" \
    token_ttl=8h token_max_ttl=24h
unset P
```

`password=-` reads the value from stdin, so it never shows up in your shell history. Alice then logs in with `bao login -method=userpass username=alice` and gets a short-lived token with exactly the same access. Keep the token roles from §3 for scripts or tools that can't log in.
