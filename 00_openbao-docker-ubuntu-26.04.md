# Installing OpenBao as a container on Ubuntu 26.04 LTS

A single-node OpenBao server running in Docker with **Raft storage**, **TLS** and the **web UI**. It's suitable as the secrets backend for Ansible/AVD.

| Item | Value |
|---|---|
| Host OS | Ubuntu 26.04 LTS (Resolute Raccoon) |
| Container runtime | Docker Engine + Compose plugin (official Docker repo) |
| Image | `quay.io/openbao/openbao:2.7.2` (same image as `openbao/openbao` on Docker Hub) |
| Storage | Integrated Raft, persisted in a named Docker volume |
| Ports | `8200` (API/UI), `8201` (cluster, only needed for HA later) |
| Install directory | `/opt/openbao` |

> **Version note:** OpenBao 2.7 removed the `file` storage backend. Use `raft` (as below) or PostgreSQL. Pin a specific version tag instead of using `latest`.

---

## 1. Prepare the host

Create a DNS record (or `/etc/hosts` entry) for the server, e.g. `openbao.kloud.lan`. This guide uses that name throughout.

## 2. Install Docker Engine

Use Docker's official repository rather than Ubuntu's `docker.io` package, which is older.

```bash
# Remove conflicting packages (harmless on a fresh install)
for p in docker.io docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt remove -y $p 2>/dev/null
done

# Docker GPG key and repository
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker

# Optional: run docker without sudo (log out and back in afterwards)
sudo usermod -aG docker $USER
```

Verify:

```bash
docker version --format '{{.Server.Version}}'
docker compose version
```

## 3. Create the directory layout

```bash
sudo mkdir -p /opt/openbao/config/tls
sudo chown -R $USER: /opt/openbao
cd /opt/openbao
```

Final layout:

```
/opt/openbao/
├── compose.yaml
└── config/
    ├── openbao.hcl
    └── tls/
        ├── bao.crt
        └── bao.key
```

## 4. TLS certificate

**Option A — certificate from your internal CA (recommended).** Issue a server certificate for `openbao.kloud.lan` (SAN must include the DNS name and IP you connect with). Then copy the cert (with the chain) to `config/tls/bao.crt` and the key to `config/tls/bao.key`.

**Option B — self-signed (lab only):**

```bash
openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 -nodes -days 825 \
  -keyout config/tls/bao.key -out config/tls/bao.crt \
  -subj "/CN=openbao.kloud.lan" \
  -addext "subjectAltName=DNS:openbao.kloud.lan,DNS:localhost,IP:127.0.0.1,IP:<SERVER_IP>"
```

The container runs as the non-root `openbao` user, so that user must be able to read the key. Check its UID/GID, then set ownership:

```bash
docker run --rm --entrypoint id quay.io/openbao/openbao:2.7.2 openbao
# example output: uid=100(openbao) gid=1000(openbao)

sudo chown 100:1000 config/tls/bao.key     # use the UID:GID printed above
sudo chmod 600 config/tls/bao.key
chmod 644 config/tls/bao.crt
```

## 5. Server configuration

`config/openbao.hcl`:

```hcl
ui            = true
disable_mlock = true   # recommended with Raft storage

api_addr     = "https://openbao.kloud.lan:8200"
cluster_addr = "https://openbao.kloud.lan:8201"

storage "raft" {
  path    = "/openbao/file"
  node_id = "bao-1"
}

listener "tcp" {
  address       = "0.0.0.0:8200"
  tls_cert_file = "/openbao/config/tls/bao.crt"
  tls_key_file  = "/openbao/config/tls/bao.key"
}
```

> The Raft data lives in `/openbao/file`. That path already exists in the image with the right owner, so Docker gives the new named volume the correct permissions automatically. If you use a different path (e.g. `/openbao/data`), you'll have to `chown` the volume to the `openbao` user yourself.

## 6. Compose file

`compose.yaml`:

```yaml
# Start the deployment
#   docker compose --file /opt/openbao/compose.yaml up --detach
#   docker compose --file /opt/openbao/compose.yaml up --detach --remove-orphans
#   docker compose --file /opt/openbao/compose.yaml restart
# Destroy the deployment
#   docker compose --file /opt/openbao/compose.yaml down --remove-orphans
# Stop by keeps everything
#   docker compose --file /opt/openbao/compose.yaml stop
#   docker compose --file /opt/openbao/compose.yaml rm --force
# List the running container
#   docker ps --format 'table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}'
# Jump inside a container
#   docker exec -it openbao /bin/sh
# Check logs
#   docker compose --file /opt/openbao/compose.yaml logs
# Restart bind
#   docker kill -s HUP openbao

# ------------------------------------------------#
#        OpenBao Container
# ------------------------------------------------#
services:
  openbao:
    image: quay.io/openbao/openbao:2.7.3
    container_name: openbao
    command: server
    restart: unless-stopped
    cap_add: [IPC_LOCK]
    environment:
      BAO_ADDR: https://127.0.0.1:8200
      BAO_CACERT: /openbao/config/tls/bao.crt
      SKIP_CHOWN: "true"          # config is mounted read-only
    ports:
      - "8200:8200"
      - "8201:8201"
    volumes:
      - ./config:/openbao/config:ro
      - bao-data:/openbao/file
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  bao-data:
```

Start it:

```bash
docker compose --file /opt/openbao/compose.yaml up --detach
docker logs -f openbao      # wait for: "==> OpenBao server started!"
```

## 7. Initialize and unseal

Initialization happens **once**. It prints the unseal keys and the initial root token.

```bash
docker exec -it openbao bao operator init -key-shares=5 -key-threshold=3
```

> ⚠️ **Store the 5 unseal keys and the root token securely and separately** (e.g. split between people or a password manager). If you lose them, you can't get the data back.

Example of the output from command above:

```text
Unseal Key 1: ZTfsbVACt5cAcJbAQRnw1aPUVeNjHVsn0kymPdcPN61d
Unseal Key 2: ojRRaX4/8y5nNRIcFGkrjyqRg2IxWHm/ts2tSE4aQj3N
Unseal Key 3: Mn8RhrF6l4tv/6upZx+IHxFTFOtFJKE+BCc6JpBNpWRb
Unseal Key 4: rG2eYGDD1VWMdw+1sGb9MyO+1UpYjrev1rc5sOjaNVsK
Unseal Key 5: HXrLt10JpC0d+/2riL+jeBj6phey5ttR4dbBA1r6Yy7W

Initial Root Token: s.zXHWGfCEOA6fnN54C4rpej3n

Vault initialized with 5 key shares and a key threshold of 3. Please securely
distribute the key shares printed above. When the Vault is re-sealed,
restarted, or stopped, you must supply at least 3 of these keys to unseal it
before it can start servicing requests.

Vault does not store the generated root key. Without at least 3 keys to
reconstruct the root key, Vault will remain permanently sealed!

It is possible to generate new unseal keys, provided you have a quorum
of existing unseal keys shares. See "bao operator rotate-keys" for more
information.
```

🔓 Unseal with any 3 of the 5 keys (run 3 times, pasting a different key each time):

```bash
docker exec -it openbao bao operator unseal
```

Check:

```bash
docker exec openbao bao status
```

```text
Key                     Value
---                     -----
Seal Type               shamir
Initialized             true  👈👈👈
Sealed                  false 👈👈👈
Total Shares            5
Threshold               3
Version                 2.7.2
Commit Date             2026-10-26T20:32:27Z
Storage Type            raft
Cluster Name            vault-cluster-9871ef1f
Cluster ID              7c9e0d05-b58c-ce08-db36-2f36d8520e28
HA Enabled              true
HA Cluster              https://openbao.kloud.lan:8201
HA Mode                 active
Active Since            2026-11-22T00:21:03.918979766Z
Raft Committed Index    179
Raft Applied Index      179
```

> OpenBao **re-seals on every restart** (container, Docker or host reboot). You have to repeat the unseal step each time, or set up auto-unseal.

## 8. Log in and verify

```bash
docker exec -it openbao bao login          # paste the root token (s.zXHWGfCEOA6fnN54C4rpej3n)
docker exec openbao bao secrets list
```

Output:
```text
Path          Type         Accessor              Description
----          ----         --------              -----------
cubbyhole/    cubbyhole    cubbyhole_07288d42    per-token private secret storage
identity/     identity     identity_d0b7fe4b     identity store
sys/          system       system_0e360966       system endpoints used for control, policy and debugging
```

Web UI: `https://openbao.kloud.lan:8200/ui`

## 9. Firewall

Docker-published ports **bypass UFW** (Docker writes its own iptables rules). Two ways to limit access:

- **Bind to one interface** in `compose.yaml`, e.g. `"10.0.0.5:8200:8200"`. For local-only access use `"127.0.0.1:8200:8200"`.
- **Filter in the `DOCKER-USER` chain**, e.g. allow only your management subnet:

```bash
sudo iptables -I DOCKER-USER -p tcp --dport 8200 ! -s 10.0.0.0/24 -j DROP
```

(Persist with `iptables-persistent`, or manage it through your usual tooling.)

## 10. Post-install hardening

1. **Create an admin policy and user instead of using root**, then revoke the root token:
```bash
docker exec -i openbao bao policy write admin - <<'EOF'
path "*" { capabilities = ["create","read","update","delete","list","sudo"] }
EOF
docker exec openbao bao auth enable userpass
# password=- reads stdin silently (no prompt), so pipe it in with -i (not -it)
read -rsp "Password: " PW; echo
printf '%s' "$PW" | docker exec -i openbao bao write auth/userpass/users/daniel password=- policies=admin
unset PW

# Test the new login (this one prompts)
docker exec -it openbao bao login -method=userpass username=daniel

docker exec openbao bao token revoke -self   # only after verifying the admin login works
```
   You can create a new root token later with `bao operator generate-root` and the unseal keys.

2. **Enable an audit log.** OpenBao refuses to create audit devices through the API (`bao audit enable` returns `cannot enable audit device via API`), so declare it in `config/openbao.hcl`:
```hcl
audit "file" "file" {
  description = "Local audit log"
  options {
    file_path = "/openbao/logs/audit.log"
    mode      = "0600"
  }
}
```
   Add a `bao-logs:/openbao/logs` volume in `compose.yaml` (and `bao-logs:` under `volumes:`), then run `docker compose up -d`, unseal and check with `bao audit list`.
   Later changes to the `audit` block only need `docker kill -s HUP openbao`, with no restart or re-seal.

3. **Back up Raft regularly:**
```bash
docker exec openbao bao operator raft snapshot save /tmp/bao.snap
mkdir -p backup
docker cp openbao:/tmp/bao.snap ./backup/bao-$(date +%F).snap
```

> Restore with `bao operator raft snapshot restore`.

## Section 11: next steps

These are optional improvements once the basic server works.

**Auto-unseal.** OpenBao encrypts its data with a master key. At startup that key is locked ("sealed"), which is why you paste 3 of the 5 keys after every restart. With auto-unseal, OpenBao asks a trusted outside service to unlock the key for it, so it unseals itself:
- **Transit seal:** a second small OpenBao instance holds the key. It's free and self-hosted, but that second instance has to be unsealed by hand.
- **Cloud KMS or HSM:** AWS KMS, Azure Key Vault, GCP KMS or a PKCS#11 HSM. Several provider-specific built-in seals will be removed from OpenBao in v2.7.0 and remain available as external plugins only. So in 2.7 you add the matching plugin as well as the `seal` block.

For a single lab server, unsealing by hand is fine. Auto-unseal is worth setting up once switch deployments depend on OpenBao being available.

**High availability.** One node is a single point of failure: if it's down, AVD can't fetch its secrets. Raft can run as a cluster. You add 2 more OpenBao nodes, each with a `retry_join` pointing at the others. One node is active and the rest are standbys that copy its data. With 3 nodes, one can fail and the cluster keeps working. This is what port 8201 (`cluster_addr`) is for.

**Upgrades.** Before every upgrade, take a Raft snapshot so you can roll back. Then change the image tag in `compose.yaml` and recreate the container. The container restarts, so you unseal again. Read the release notes first, since 2.7 removing the `file` backend shows they can contain breaking changes.

## Section 12: Install OpenBAO cli

Install OpenBAO cli on Ubuntu 26.04 LTS for either `amd64` or `arm64`:

```bash
TARGETARCH=$(dpkg --print-architecture)
BAO_VERSION=$(curl -fsSL https://api.github.com/repos/openbao/openbao/releases/latest | jq -er '.tag_name')
BAO_FILE="openbao_${BAO_VERSION#v}_linux_${TARGETARCH}.tar.gz"
BASE_URL="https://github.com/openbao/openbao/releases/download/${BAO_VERSION}"

echo "Installing OpenBao CLI ${BAO_VERSION} for ${TARGETARCH}"
curl -fsSLO "${BASE_URL}/${BAO_FILE}" && \
curl -fsSL "${BASE_URL}/checksums.txt" | grep " ${BAO_FILE}$" | sha256sum -c - && \
sudo tar -C /usr/local/bin --no-same-owner -xzf "${BAO_FILE}" bao && \
rm -f "${BAO_FILE}" && \
bao version
```

> [!NOTE] The `bao` cli should be installed in the Dev Container.  

## Section 13: using it from Ansible / AVD

This connects the server to the AVD project from earlier.

**1. Seed the secrets.** `seed-openbao.sh` creates the `network/` store, stores your BGP and TACACS secrets, creates the `avd-readonly` policy, and sets up AppRole. It needs the `bao` CLI on the machine where you run it. You can either install `bao` on your Ansible host, or copy the script into the container and run it there:

```bash
docker cp scripts/seed-openbao.sh openbao:/tmp/
docker exec -it openbao sh /tmp/seed-openbao.sh
```

**2. Give Ansible a limited token.** Don't use your `daniel` admin login for Ansible:

```bash
docker exec openbao bao token create -policy=avd-readonly -ttl=8h
```

That token can only read `network/fabric/*`, and it expires on its own. For CI/CD, use the AppRole `role_id` and `secret_id` the script prints instead.

**3. Point Ansible at the server:**

```bash
export VAULT_ADDR=https://openbao.kloud.lan:8200
export VAULT_CACERT="$(realpath bao-cert/openbao.kloud.lan-chain.pem)"
export VAULT_TOKEN=s.zXHWGfCEOA6fnN54C4rpej3n   # token from step 2
make build ENV=net-prod
```

- `VAULT_ADDR` tells the `community.hashi_vault` lookups in `global_vars/secret.yml` where the server is.
- `VAULT_CACERT` lets Ansible trust your certificate. Without it you get an `x509` error.
- `VAULT_TOKEN` is the token that authorizes the reads.

The `VAULT_*` names are correct even though the server is OpenBao: the Ansible collection only reads those names.

When you run the build, each `{{ lookup(...) }}` in `secret.yml` fetches its value from OpenBao. AVD then encrypts it into the switch config. If the token is missing, expired or lacks permission, the build fails with a `permission denied` error.

---

## Quick troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `permission denied` on `bao.key` | Key not readable by the container's `openbao` UID (see §4) |
| `failed to open database ... permission denied` | Raft path isn't `/openbao/file`, so `chown` the volume |
| `unknown storage type file` after upgrade | 2.7+ dropped `file`; migrate to Raft with `bao operator migrate` |
| `x509: certificate signed by unknown authority` | Client is missing `BAO_CACERT` / `VAULT_CACERT` |
| `cannot enable audit device via API` | Expected in 2.4+; declare an `audit` stanza in the config (§10) |
| `Vault is sealed` / HTTP 503 after reboot | Unseal again (§7) or configure auto-unseal |
