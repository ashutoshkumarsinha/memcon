.DEFAULT_GOAL := help

DEVBOX    ?= devbox
PYTHON    ?= python3
PYTEST    ?= pytest
# Leave PROVIDER unset to use config.toml flags (use_ollama / use_paid / use_kiro).
PROVIDER  ?=
MODEL     ?=
ARGS      ?=

VERSION   := $(shell grep -E '^version\s*=' config.toml | head -1 | cut -d'"' -f2)
BINARY    := dist/memcon
RELEASE   := releases/memcon-v$(VERSION)-host.tar.gz

ifdef MODEL
MODEL_FLAG := -m $(MODEL)
else
MODEL_FLAG :=
endif

ifdef PROVIDER
PROVIDER_FLAG := --provider $(PROVIDER)
else
PROVIDER_FLAG :=
endif

RUN_FLAGS := $(PROVIDER_FLAG) $(MODEL_FLAG) $(ARGS)

.PHONY: help install shell test verify build clean run version checksum \
        show-context run-ollama run-anthropic run-openai run-kiro run-paid

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_.-]+:.*##' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Variables: ARGS, MODEL, PROVIDER (omit to use config.toml flags)"

install: ## Install devbox packages
	$(DEVBOX) install

shell: ## Enter devbox development shell
	$(DEVBOX) shell

test: ## Run pytest suite
	$(DEVBOX) run test

verify: test ## Alias for test

build: ## Build release artifacts (tests run inside build.sh)
	$(DEVBOX) run build

run: ## Run memcon (ARGS='"prompt" --scan'; PROVIDER overrides config.toml)
	$(PYTHON) memcon.py $(RUN_FLAGS)

show-context: ## Preview assembled prompt (ARGS='"prompt" --scan')
	$(PYTHON) memcon.py $(RUN_FLAGS) --show-context

run-ollama: ## Run with Ollama (--provider ollama)
	$(MAKE) run PROVIDER=ollama

run-anthropic: ## Run with Anthropic (--provider anthropic)
	$(MAKE) run PROVIDER=anthropic

run-openai: ## Run with OpenAI (--provider openai)
	$(MAKE) run PROVIDER=openai

run-kiro: ## Run with Kiro CLI (--provider kiro)
	$(MAKE) run PROVIDER=kiro

run-paid: ## Run with paid provider from config.toml (use_paid + paid_provider)
	$(MAKE) run

version: ## Print memcon version
	$(PYTHON) memcon.py --version

checksum: ## Verify release SHA-256 manifest
	@cd releases && shasum -a 256 -c SHASUMS256.txt

clean: ## Remove build and cache artifacts
	rm -rf dist build releases .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -f memcon.spec
