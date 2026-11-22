.PHONY: help
help: ## Display help message (*: main entry points / []: part of an entry point)
	@grep -E '^[0-9a-zA-Z_-]+\.*[0-9a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

# make build ENV=net-prod             # all DCs
# make build ENV=net-prod DC=DC1      # DC1 only
.PHONY: build
build: ## build configurations. Specify ENV=<net-prod|net-staging|net-lab> and optionally DC=<DC1|DC2|DC3>
	@case "$(ENV)" in net-prod|net-staging|net-lab) ;; *) printf 'Usage: make build ENV=<net-prod|net-staging|net-lab>\n' >&2; exit 2 ;; esac
	@case "$(DC)" in ""|DC1|DC2|DC3) ;; *) printf 'Usage: make build ENV=<net-prod|net-staging|net-lab> [DC=<DC1|DC2|DC3>]\n' >&2; exit 2 ;; esac
	ansible-playbook -i inventories/$(ENV)/inventory.yml -e "ENV=$(ENV)" $(if $(DC),--limit "$(DC)",) playbooks/build.yml
