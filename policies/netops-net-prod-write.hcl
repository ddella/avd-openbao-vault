# netops-net-prod-write.hcl
path "net-prod/data/*"       { capabilities = ["create", "read", "update", "patch"] }
path "net-prod/metadata/*"   { capabilities = ["read", "list", "patch"] }
path "net-prod/delete/*"     { capabilities = ["update"] }
path "net-prod/undelete/*"   { capabilities = ["update"] }
