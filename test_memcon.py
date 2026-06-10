#!/usr/bin/env python3
import json
import pytest
from pathlib import Path
import memcon

# =====================================================================
# 1. CORE TOKEN ESTIMATOR TESTING MATRIX
# =====================================================================

def test_token_calculator_plain_text():
    """Validates that plain English text estimates match expected narrative parsing weights."""
    sample_text = "This is a clean sentence explaining user goals to a model."
    expected_tokens = len(sample_text) // 3.9
    assert memcon.calculate_precise_tokens(sample_text) == int(expected_tokens)

def test_token_calculator_dense_code():
    """Ensures token calculations weight syntax symbols higher due to denser code tokens."""
    code_block = "def fetch_nodes(ctx: dict) -> list:\n    return [x for x in ctx if x.active]"
    expected_tokens = len(code_block) // 3.4
    assert memcon.calculate_precise_tokens(code_block) == int(expected_tokens)


# =====================================================================
# 2. FILE SCANNING AND `.memconignore` COMPLIANCE TESTING
# =====================================================================

def test_ignore_rules_matching(tmp_path):
    """Verifies standard and custom ignore rules drop files from being parsed."""
    root_dir = tmp_path
    ignore_rules = ["*.log", "secrets/", "config/local.json"]

    # Invariant default folder check
    assert memcon.is_ignored(root_dir / "node_modules" / "pkg.js", root_dir, ignore_rules) is True
    assert memcon.is_ignored(root_dir / ".git" / "HEAD", root_dir, ignore_rules) is True

    # Custom file pattern rule evaluations
    assert memcon.is_ignored(root_dir / "debug.log", root_dir, ignore_rules) is True
    assert memcon.is_ignored(root_dir / "secrets" / "credentials.txt", root_dir, ignore_rules) is True
    assert memcon.is_ignored(root_dir / "config" / "local.json", root_dir, ignore_rules) is True

    # Allowed baseline code script matching validations
    assert memcon.is_ignored(root_dir / "main.py", root_dir, ignore_rules) is False
    assert memcon.is_ignored(root_dir / "src" / "index.ts", root_dir, ignore_rules) is False


# =====================================================================
# 3. PRE-FLIGHT SYNTAX RUNTIME INTERCEPTION TESTING
# =====================================================================

def test_syntax_checker_valid_python(tmp_path):
    """Ensures syntactically sound Python files pass pre-flight checks."""
    valid_file = tmp_path / "valid.py"
    valid_file.write_text("def hello():\n    print('Hello World')\n")
    
    is_valid, err = memcon.check_syntax_validity(valid_file)
    assert is_valid is True
    assert err == ""

def test_syntax_checker_invalid_python(tmp_path):
    """Ensures uncompilable code triggers a SyntaxError, capturing the line number."""
    broken_file = tmp_path / "broken.py"
    # Unclosed parentheses error
    broken_file.write_text("def crash_engine(\n    print('Oops')\n")
    
    is_valid, err = memcon.check_syntax_validity(broken_file)
    assert is_valid is False
    assert "Line" in err  # Confirms message returns location metadata


# =====================================================================
# 4. ADAPTIVE CONTEXT COMPRESSION SAFE BUDGET TESTING
# =====================================================================

def test_workspace_compression_drops_excess_files(tmp_path):
    """Checks that the workspace compressor drops files to stay within the token budget."""
    root_dir = tmp_path
    
    # Create two workspace sample code files
    file_a = root_dir / "module_a.py"
    file_b = root_dir / "module_b.py"
    
    file_a.write_text("def function_a(): pass") # Length 22 chars -> ~6 tokens
    file_b.write_text("def function_b(): pass") # Length 22 chars -> ~6 tokens

    # Set an artificial, low budget limit of 15 tokens
    # Baseline uses 10 tokens, leaving only 5 tokens available
    baseline_tokens = 10
    max_budget_limit = 15

    # Run the file ingestion cycle
    context_output = memcon.scan_and_compress_workspace(root_dir, baseline_tokens, max_budget_limit)
    
    # The workspace text output should include file A but drop file B to respect the token cap
    assert "module_a.py" in context_output
    assert "module_b.py" not in context_output


# =====================================================================
# 5. REST CLIENT payload INTEGRATION TESTING
# =====================================================================

def test_config_loads_from_toml():
    """Ensures config.toml is parsed and exposes expected defaults."""
    cfg = memcon.load_config(memcon._bundle_dir() / "config.toml")
    assert cfg.version == "1.0"
    assert cfg.provider_name == "ollama"
    assert cfg.default_model == "llama3"
    assert cfg.provider.base_url == "http://localhost:11434"
    assert cfg.default_budget_tokens == 4000
    assert cfg.scan_max_depth == 3


def _provider_config(tmp_path: Path, **overrides: bool | str) -> Path:
    text = (memcon._bundle_dir() / "config.toml").read_text()
    for key, value in overrides.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
            text = text.replace(f"{key} = true", f"{key} = {rendered}")
            text = text.replace(f"{key} = false", f"{key} = {rendered}")
        else:
            text = text.replace(f'{key} = "anthropic"', f'{key} = "{value}"')
            text = text.replace(f'{key} = "openai"', f'{key} = "{value}"')
    config = tmp_path / "config.toml"
    config.write_text(text)
    return config


def test_provider_flags_paid_anthropic(tmp_path):
    """Ensures use_paid + paid_provider selects Anthropic."""
    cfg = memcon.load_config(
        _provider_config(tmp_path, use_ollama=False, use_paid=True)
    )
    assert cfg.provider_name == "anthropic"
    assert cfg.default_model == "claude-sonnet-4-20250514"


def test_provider_flags_kiro(tmp_path):
    """Ensures use_kiro selects the Kiro CLI backend."""
    cfg = memcon.load_config(
        _provider_config(tmp_path, use_ollama=False, use_kiro=True)
    )
    assert cfg.provider_name == "kiro"
    assert cfg.provider.cli_path == "kiro-cli"


def test_provider_flags_reject_multiple_enabled(tmp_path):
    """Ensures only one provider flag may be enabled."""
    with pytest.raises(ValueError, match="Multiple providers enabled"):
        memcon.load_config(
            _provider_config(tmp_path, use_ollama=True, use_kiro=True)
        )


def test_provider_legacy_name_fallback(tmp_path):
    """Falls back to [provider].name when all use_* flags are false."""
    config = tmp_path / "config.toml"
    config.write_text(
        (memcon._bundle_dir() / "config.toml").read_text().replace(
            "use_ollama = true",
            "use_ollama = false",
        ).replace('name = "ollama"', 'name = "openai"')
    )
    cfg = memcon.load_config(config)
    assert cfg.provider_name == "openai"


def test_provider_config_anthropic():
    """Ensures Anthropic provider settings load from config.toml."""
    cfg = memcon.load_config(
        memcon._bundle_dir() / "config.toml",
        provider_name="anthropic",
    )
    assert cfg.provider_name == "anthropic"
    assert cfg.provider.api_key_env == "ANTHROPIC_API_KEY"
    assert cfg.default_model == "claude-sonnet-4-20250514"
    assert cfg.provider.endpoint == "/v1/messages"


def test_provider_config_kiro():
    """Ensures Kiro CLI provider settings load from config.toml."""
    cfg = memcon.load_config(
        memcon._bundle_dir() / "config.toml",
        provider_name="kiro",
    )
    assert cfg.provider_name == "kiro"
    assert cfg.provider.mode == "acp"
    assert cfg.provider.cli_path == "kiro-cli"
    assert cfg.provider.api_key_env == "KIRO_API_KEY"
    assert cfg.provider.auto_approve_tools is True


def test_kiro_prompt_formatting():
    """Ensures memcon messages are flattened for kiro-cli ACP prompts."""
    from providers.kiro import _format_prompt

    prompt = _format_prompt(
        "You are helpful.",
        [
            {"role": "user", "content": "Workspace files:\ncode"},
            {"role": "user", "content": "Refactor auth"},
        ],
    )
    assert "# System instructions" in prompt
    assert "Refactor auth" in prompt
    assert "Workspace files" in prompt


def test_provider_config_openai():
    """Ensures OpenAI provider settings load from config.toml."""
    cfg = memcon.load_config(
        memcon._bundle_dir() / "config.toml",
        provider_name="openai",
    )
    assert cfg.provider_name == "openai"
    assert cfg.provider.api_key_env == "OPENAI_API_KEY"
    assert cfg.default_model == "gpt-4o"


def test_split_messages_extracts_system_prompt():
    """Ensures system content is split from conversation messages."""
    from providers.messages import split_messages

    system, conversation = split_messages(
        [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Workspace files:\ncode"},
            {"role": "user", "content": "Do the thing"},
        ]
    )
    assert system == "You are helpful."
    assert len(conversation) == 2
    assert conversation[-1]["content"] == "Do the thing"


def test_dynamic_budget_mapping():
    """Ensures context token limits automatically scale based on the target model size."""
    assert memcon.get_dynamic_budget("llama3:8b") == 4000
    assert memcon.get_dynamic_budget("qwen2.5:14b") == 8000
    assert memcon.get_dynamic_budget("codestral:32b") == 8000
    assert memcon.get_dynamic_budget("llama3:70b") == 16000
    assert memcon.get_dynamic_budget("unknown_model_name") == 4000  # Secure default fallback
