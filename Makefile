# Convenience shortcuts for the Zabbix 7.0 learning stack.
# Run `make help` to see targets.

.DEFAULT_GOAL := help
.PHONY: help up down reset logs ps venv bootstrap add-hosts maps hosts api-version \
	scenario-list scenario scenario-hint scenario-verify scenario-reveal scenario-reset scenario-status

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

up: ## Start the whole stack in the background
	docker compose up -d

down: ## Stop and remove containers, KEEP the database volume
	docker compose down

reset: ## Stop everything AND delete the db volume (full clean reset)
	docker compose down -v

logs: ## Tail the zabbix-server logs
	docker compose logs -f zabbix-server

ps: ## Show running services and port mappings
	docker compose ps

venv: ## Create the Python venv and install dependencies
	python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

bootstrap: ## Configure the sample agent host/items/triggers via the API
	. .venv/bin/activate && python scripts/bootstrap.py

add-hosts: ## Add hosts of different types (agent/SNMP/ICMP/HTTP) + locations
	. .venv/bin/activate && python scripts/add_hosts.py

maps: ## Build the network map + geomap dashboard
	. .venv/bin/activate && python scripts/create_maps.py

hosts: ## List all hosts via the API
	. .venv/bin/activate && python scripts/list_hosts.py

api-version: ## Confirm the API is reachable (no auth)
	curl -s -X POST $${ZABBIX_URL:-http://localhost:8080}/api_jsonrpc.php \
		-H "Content-Type: application/json-rpc" \
		-d '{"jsonrpc":"2.0","method":"apiinfo.version","params":{},"id":1}'
	@echo

scenario-list: ## List troubleshooting lab scenarios (see scenarios/GUIDE.md)
	.venv/bin/python scripts/scenario_lab.py list

scenario-status: ## Show active scenario (if any)
	.venv/bin/python scripts/scenario_lab.py status

scenario: ## Start a scenario: make scenario SCENARIO=agent-down
	@test -n "$(SCENARIO)" || (echo "Usage: make scenario SCENARIO=agent-down" && exit 1)
	.venv/bin/python scripts/scenario_lab.py start $(SCENARIO)

scenario-hint: ## Next hint for the active scenario
	.venv/bin/python scripts/scenario_lab.py hint

scenario-verify: ## Check whether you fixed the active scenario
	.venv/bin/python scripts/scenario_lab.py verify

scenario-reveal: ## Show the intended fix (spoiler)
	.venv/bin/python scripts/scenario_lab.py reveal

scenario-reset: ## Undo the active scenario injection
	.venv/bin/python scripts/scenario_lab.py reset
