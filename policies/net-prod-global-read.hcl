# net-prod-global-read.hcl
# Read-only access to environment-wide secrets. Attach to every net-prod token.
path "net-prod/data/global/*"      { capabilities = ["read"] }
path "net-prod/metadata/global/*"  { capabilities = ["read", "list"] }

# Navigation only: list the top of the mount (shows "global/" and "dc/" names, no values)
path "net-prod/metadata/"          { capabilities = ["list"] }
