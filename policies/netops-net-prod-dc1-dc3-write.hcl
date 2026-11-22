# netops-net-prod-dc1-dc3-write.hcl
# Read/write DC1 and DC3 only. DC2 (and any future DC) stays denied.
path "net-prod/data/dc/dc1/*"       { capabilities = ["create", "read", "update", "patch"] }
path "net-prod/metadata/dc/dc1/*"   { capabilities = ["read", "list", "patch"] }
path "net-prod/delete/dc/dc1/*"     { capabilities = ["update"] }
path "net-prod/undelete/dc/dc1/*"   { capabilities = ["update"] }

path "net-prod/data/dc/dc3/*"       { capabilities = ["create", "read", "update", "patch"] }
path "net-prod/metadata/dc/dc3/*"   { capabilities = ["read", "list", "patch"] }
path "net-prod/delete/dc/dc3/*"     { capabilities = ["update"] }
path "net-prod/undelete/dc/dc3/*"   { capabilities = ["update"] }

# Navigation only: list the DC names under dc/ (shows "dc2/" as a name, never its values)
path "net-prod/metadata/dc/"        { capabilities = ["list"] }
