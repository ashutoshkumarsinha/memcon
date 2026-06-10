.DEFAULT_GOAL := help

DEVBOX    ?= devbox
PYTHON    ?= python3
PYTEST    ?= pytest
PROVIDER  ?= ollama
MODEL     ?=
ARGS      ?=

VERSION   := $(shell grep -E '^version\s*=' config.toml | head -1 | cut -d'"' -f2)
BINARY    := dist/memcon
RELEASE   := releases/memcon-v$(VERSION)-host.tar.gz

# Optional model flag for run targets
ifdef MODEL
MODEL_FLAG := -m $(MODEL)
else
MODEL_FLAG :=
endif

RUN_FLAGS := --provider $(PROVIDER) $(MODEL_FLAG) $(ARGS)

.PHONY: help install shell test verify build clean run version checksum \
        show-context run-ollama run-anthropic run-openai run-kiro

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_.-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install devbox packages
	$(DEVBOX) install

shell: ## Enter devbox development shell
	$(DEVBOX) shell

test: ## Run pytest suite
	$(DEVBOX) run test

verify: test ## Alias for test

build: ## Build release artifacts (tests run inside build.sh)
	./build.sh

run: ## Run memcon (PROVIDER=ollama ARGS='"prompt" --scan')
	$(PYTHON) memcon.py $(RUN_FLAGS)

show-context: ## Preview assembled prompt (ARGS='"prompt" --scan')
	$(PYTHON) memcon.py $(RUN_FLAGS) --show-context

run-ollama: ## Run with Ollama provider
	$(MAKE) run PROVIDER=ollama

run-anthropic: ## Run with Anthropic provider
	$(MAKE) run PROVIDER=anthropic

run-openai: ## Run with OpenAI provider
	$(MAKE) run PROVIDER=openai

run-kiro: ## Run with Kiro CLI provider
	$(MAKE) run PROVIDER=kiro

version: ## Print memcon version
	$(PYTHON) memcon.py --version

checksum: ## Verify release SHA-256 manifest
	@cd releases && shasum -a 256 -c SHASUMS256.txt

clean: ## Remove build and cache artifacts
	rm -rf dist build releases .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f memcon.spec
