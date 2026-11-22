# avd-net-prod-read.hcl
path "net-prod/data/*"      { capabilities = ["read"] }
path "net-prod/metadata/*"  { capabilities = ["read"] }
