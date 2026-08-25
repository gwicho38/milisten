.DEFAULT_GOAL := help

.PHONY: help dev test lint run ui start stop open install uninstall clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

dev: ## Sync dependencies into the uv venv
	uv sync --extra dev

test: ## Run the full test suite
	uv run pytest -q

lint: ## Lint with ruff
	uv run ruff check src test

ui: ## Launch the web UI in the foreground (auto-opens the browser)
	uv run milisten ui

start: ## Start the web UI detached (survives this shell exiting)
	uv run milisten ui start

stop: ## Stop the detached web UI
	uv run milisten ui stop

open: ## Open the running web UI in a browser
	uv run milisten ui open

install: ## Install the milisten CLI globally (uv tool install)
	uv tool install --force .

uninstall: ## Remove the globally installed CLI
	uv tool uninstall milisten

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache dist build src/**/__pycache__
