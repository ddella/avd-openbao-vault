# Start OpenBao

OpenBao **re-seals on every restart** (container, Docker or host reboot). You have to repeat the unseal step each time, or set up auto-unseal.

## Step 1: 🚀 Start OpenBao container

If you shutdown the server, you'll need to restart OpenBao.

Start it:

```bash
docker compose up -d
docker logs -f openbao      # wait for: "==> OpenBao server started!"
```

## Step 2: 🔓 Unseal OpenBao

### Check the status but the server is sealed;

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

### Unseal

Unseal with any 3 of the 5 keys (run 3 times, pasting a different key each time):
```bash
docker exec -it openbao bao operator unseal
```

Output:
```text
Unseal Key 1: ZTfsbVACt5cAcJbAQRnw1aPUVeNjHVsn0kymPdcPN61d
Unseal Key 2: ojRRaX4/8y5nNRIcFGkrjyqRg2IxWHm/ts2tSE4aQj3N
Unseal Key 3: Mn8RhrF6l4tv/6upZx+IHxFTFOtFJKE+BCc6JpBNpWRb
Unseal Key 4: rG2eYGDD1VWMdw+1sGb9MyO+1UpYjrev1rc5sOjaNVsK
Unseal Key 5: HXrLt10JpC0d+/2riL+jeBj6phey5ttR4dbBA1r6Yy7W
```

### Check

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

> [!NOTE] OpenBao **re-seals on every restart** (container, Docker or host reboot). You have to repeat the unseal step each time, or set up auto-unseal.  

## Step 3: Log in and verify

```bash
docker exec -it openbao bao login -method=userpass username=daniel  # enter your password
docker exec openbao bao secrets list
```

Output:
```text
Path          Type         Accessor              Description
----          ----         --------              -----------
cubbyhole/    cubbyhole    cubbyhole_07288d42    per-token private secret storage
identity/     identity     identity_d0b7fe4b     identity store
network/      kv           kv_d6dde858           n/a
sys/          system       system_0e360966       system endpoints used for control, policy and debugging
```

---

# OpenBao cli

Execute those commands **inside** your Dev Container:

```bash
export VAULT_ADDR=https://openbao.kloud.lan:8200
export VAULT_CACERT="$(realpath bao-cert/openbao.kloud.lan-chain.pem)"
export VAULT_TOKEN=s.zXHWGfCEOA6fnN54C4rpej3n
make build ENV=net-prod
```

### Web UI

You can access the web user interface via: `https://openbao.kloud.lan:8200/ui`

---

# Troubleshooting

## User context

The importer runs as OS user `avd` from bao, so launched directly from your logged-in shell it uses the same Bao CLI context; `daniel` is the Bao identity, not the Linux username.

```bash
whoami && command -v bao && printf 'HOME=%s\n' "$HOME"
```

##

The permission probe could not reach Bao from this execution context because `VAULT_ADDR` is unset here; the container itself still shows only `network/`.

```bash
bao secrets list && bao token capabilities network/data/fabric/aaa && bao token capabilities net-prod/data/global/aaa
```