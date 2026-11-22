# netops-net-prod-dc-all-write.hcl
# Read/write every data center under net-prod/dc/*
path "net-prod/data/dc/*"       { capabilities = ["create", "read", "update", "patch"] }
path "net-prod/metadata/dc/*"   { capabilities = ["read", "list", "patch"] }
path "net-prod/delete/dc/*"     { capabilities = ["update"] }
path "net-prod/undelete/dc/*"   { capabilities = ["update"] }

# Navigation only: list the DC names under dc/
path "net-prod/metadata/dc/"    { capabilities = ["list"] }
