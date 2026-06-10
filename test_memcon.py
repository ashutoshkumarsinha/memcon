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
    assert cfg.default_model == "llama3"
    assert cfg.ollama_host == "http://localhost:11434"
    assert cfg.default_budget_tokens == 4000
    assert cfg.scan_max_depth == 3


def test_dynamic_budget_mapping():
    """Ensures context token limits automatically scale based on the target model size."""
    assert memcon.get_dynamic_budget("llama3:8b") == 4000
    assert memcon.get_dynamic_budget("qwen2.5:14b") == 8000
    assert memcon.get_dynamic_budget("codestral:32b") == 8000
    assert memcon.get_dynamic_budget("llama3:70b") == 16000
    assert memcon.get_dynamic_budget("unknown_model_name") == 4000  # Secure default fallback
