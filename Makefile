.DEFAULT_GOAL := help

DEVBOX   ?= devbox
PYTHON   ?= python3
PYTEST   ?= pytest
PYINSTALLER ?= pyinstaller

VERSION  := 1.0
BINARY   := dist/memcon
RELEASE  := releases/memcon-v$(VERSION)-host.tar.gz

.PHONY: help test build clean shell run version install verify checksum

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_.-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install devbox packages
	$(DEVBOX) install

shell: ## Enter devbox development shell
	$(DEVBOX) shell

test: ## Run pytest suite
	$(DEVBOX) run test

verify: test ## Alias for test

build: ## Build release artifacts (tests run inside build.sh)
	./build.sh

run: ## Run memcon from source (usage: make run ARGS='"prompt" --scan')
	$(PYTHON) memcon.py $(ARGS)

version: ## Print memcon version
	$(PYTHON) memcon.py --version

checksum: ## Verify release SHA-256 manifest
	@cd releases && shasum -a 256 -c SHASUMS256.txt

clean: ## Remove build and cache artifacts
	rm -rf dist build releases .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f memcon.spec
