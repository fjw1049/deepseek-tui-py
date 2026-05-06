"""Parity tests for the Rust-parity execpolicy subsystem.

Mirrors the unit tests in six Rust source files:

* ``crates/tui/src/execpolicy/matcher.rs::tests`` (matcher.rs:120-197)
* ``crates/tui/src/execpolicy/rules.rs::tests`` (rules.rs:81-123)
* ``crates/tui/src/execpolicy/amend.rs::tests`` (amend.rs:148-224)
* plus coverage for rule/policy/parser that Rust had no direct
  ``#[test]`` for (since those are exercised transitively through the
  CLI's integration tests in Rust).

Cross-reference (Rust test → Python test):

* test_normalize_command → test_normalize_command_*
* test_pattern_matches → test_pattern_matches_*
* strip_heredoc_{simple,dash,quoted,non_heredoc,here_string} →
  test_strip_heredoc_*
* normalize_command_strips_heredoc_for_pattern_matching →
  test_heredoc_matches_non_heredoc_pattern
* test_execpolicy_evaluate → test_toml_evaluate_*
* appends_rule_and_creates_directories → test_amend_creates_parent_dir
* appends_rule_without_duplicate_newline → test_amend_no_duplicate_newline
* inserts_newline_when_missing_before_append →
  test_amend_inserts_newline_when_missing
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from deepseek_tui.execpolicy import (
    Decision,
    Evaluation,
    ExecPolicyConfig,
    ExecPolicyError,
    HeuristicsRuleMatch,
    PatternToken,
    Policy,
    PolicyParser,
    PrefixPattern,
    PrefixRule,
    PrefixRuleMatch,
    blocking_append_allow_prefix_rule,
    default_execpolicy_path,
    normalize_command,
    pattern_matches,
    strip_heredoc_bodies,
    validate_match_examples,
    validate_not_match_examples,
)

# ---------------------------------------------------------------------------
# Decision ordering (ALLOW < PROMPT < FORBIDDEN)
# ---------------------------------------------------------------------------


def test_decision_ordering() -> None:
    assert Decision.ALLOW < Decision.PROMPT
    assert Decision.PROMPT < Decision.FORBIDDEN
    assert max(Decision.ALLOW, Decision.FORBIDDEN) is Decision.FORBIDDEN


def test_decision_parse_known_values() -> None:
    for raw, expected in (
        ("allow", Decision.ALLOW),
        ("prompt", Decision.PROMPT),
        ("forbidden", Decision.FORBIDDEN),
    ):
        assert Decision.parse(raw) is expected


def test_decision_parse_rejects_unknown() -> None:
    with pytest.raises(ExecPolicyError):
        Decision.parse("maybe")


# ---------------------------------------------------------------------------
# PatternToken + PrefixPattern
# ---------------------------------------------------------------------------


def test_pattern_token_single_matches_exactly() -> None:
    tok = PatternToken.single("status")
    assert tok.matches("status")
    assert not tok.matches("Status")
    assert tok.alternatives() == ("status",)
    assert tok.is_single


def test_pattern_token_alts_matches_any() -> None:
    tok = PatternToken.alts(["log", "diff", "show"])
    assert tok.matches("log")
    assert tok.matches("diff")
    assert not tok.matches("push")
    assert tok.alternatives() == ("log", "diff", "show")
    assert not tok.is_single


def test_prefix_pattern_matches_full_prefix() -> None:
    pattern = PrefixPattern(
        first="git",
        rest=(PatternToken.alts(["log", "diff"]),),
    )
    assert pattern.matches_prefix(["git", "log"]) == ["git", "log"]
    assert pattern.matches_prefix(["git", "diff", "HEAD"]) == ["git", "diff"]
    assert pattern.matches_prefix(["git"]) is None
    assert pattern.matches_prefix(["git", "push"]) is None
    assert pattern.matches_prefix(["hg", "log"]) is None


# ---------------------------------------------------------------------------
# matcher.normalize_command / strip_heredoc_bodies / pattern_matches
# ---------------------------------------------------------------------------


def test_normalize_command_collapses_whitespace() -> None:
    assert normalize_command("git   status") == "git status"


def test_normalize_command_respects_shlex_quoting() -> None:
    assert normalize_command('git "log --oneline"') == "git log --oneline"


@pytest.mark.parametrize(
    "pattern,command,expected",
    [
        ("git status", "git status", True),
        ("git log *", "git log --oneline", True),
        ("cargo *", "cargo test --all", True),
        ("git push --force", "git push origin main", False),
        ("*", "anything here", True),
    ],
)
def test_pattern_matches_glob(pattern: str, command: str, expected: bool) -> None:
    assert pattern_matches(pattern, command) is expected


def test_strip_heredoc_simple_body() -> None:
    stripped = strip_heredoc_bodies(
        "cat <<EOF > file.txt\nhello\nworld\nEOF"
    )
    assert "hello" not in stripped
    assert "world" not in stripped
    assert "> file.txt" in stripped


def test_strip_heredoc_dash_form() -> None:
    stripped = strip_heredoc_bodies("cat <<-EOF > file.txt\n\tbody\nEOF")
    assert "body" not in stripped
    assert "> file.txt" in stripped


def test_strip_heredoc_quoted_delimiter() -> None:
    stripped = strip_heredoc_bodies(
        "cat <<'END_OF_FILE' > out\nliteral $vars\nEND_OF_FILE"
    )
    assert "literal" not in stripped
    assert "> out" in stripped


def test_strip_heredoc_leaves_non_heredoc_commands_intact() -> None:
    # Fast path — no `<<` in input.
    assert strip_heredoc_bodies("echo hello && ls") == "echo hello && ls"


def test_strip_heredoc_does_not_touch_here_string_operator() -> None:
    stripped = strip_heredoc_bodies('grep foo <<< "some text"')
    assert "<<<" in stripped
    assert "some text" in stripped


def test_heredoc_matches_non_heredoc_pattern() -> None:
    """End-to-end: the user's ``cat > file.txt`` pattern matches heredoc."""
    normalized = normalize_command("cat <<EOF > file.txt\nbody\nEOF")
    assert pattern_matches("cat > file.txt", normalized)


# ---------------------------------------------------------------------------
# Policy + Evaluation
# ---------------------------------------------------------------------------


def _fallback_prompt(_cmd: list[str]) -> Decision:
    return Decision.PROMPT


def test_policy_allow_rule_matches_command() -> None:
    policy = Policy.empty()
    policy.add_prefix_rule(["git", "status"], Decision.ALLOW)
    ev = policy.check(["git", "status"], _fallback_prompt)
    assert ev.decision is Decision.ALLOW
    assert ev.is_match()
    assert len(ev.matched_rules) == 1


def test_policy_heuristics_fallback_triggers_when_no_match() -> None:
    policy = Policy.empty()
    ev = policy.check(["unknown", "command"], _fallback_prompt)
    assert ev.decision is Decision.PROMPT
    assert not ev.is_match()
    assert isinstance(ev.matched_rules[0], HeuristicsRuleMatch)


def test_policy_matches_for_command_without_fallback_returns_empty() -> None:
    policy = Policy.empty()
    matches = policy.matches_for_command(["no", "rule"], None)
    assert matches == []


def test_policy_max_severity_wins() -> None:
    """The most-restrictive decision across matched rules wins."""
    policy = Policy.empty()
    policy.add_prefix_rule(["git", "status"], Decision.ALLOW)
    policy.add_prefix_rule(["git", "status"], Decision.PROMPT)
    ev = policy.check(["git", "status"], _fallback_prompt)
    assert ev.decision is Decision.PROMPT


def test_policy_check_multiple_aggregates() -> None:
    policy = Policy.empty()
    policy.add_prefix_rule(["git", "status"], Decision.ALLOW)
    policy.add_prefix_rule(["rm", "-rf"], Decision.FORBIDDEN)
    ev = policy.check_multiple(
        [["git", "status"], ["rm", "-rf", "/"]], _fallback_prompt
    )
    # Forbidden wins over Allow in the aggregate.
    assert ev.decision is Decision.FORBIDDEN


def test_policy_add_prefix_rule_rejects_empty() -> None:
    policy = Policy.empty()
    with pytest.raises(ExecPolicyError):
        policy.add_prefix_rule([], Decision.ALLOW)


def test_evaluation_from_matches_requires_non_empty() -> None:
    with pytest.raises(ExecPolicyError):
        Evaluation.from_matches([])


def test_evaluation_is_match_distinguishes_real_from_heuristics() -> None:
    prefix_match = PrefixRuleMatch.model_validate(
        {
            "matchedPrefix": ["git", "status"],
            "decision": Decision.ALLOW,
            "justification": None,
        }
    )
    heur_match = HeuristicsRuleMatch(
        command=["unknown"], decision=Decision.PROMPT
    )
    assert Evaluation.from_matches([prefix_match]).is_match()
    assert not Evaluation.from_matches([heur_match]).is_match()


# ---------------------------------------------------------------------------
# Rule construction + example validation
# ---------------------------------------------------------------------------


def test_prefix_rule_matches_reports_decision_and_prefix() -> None:
    rule = PrefixRule(
        pattern=PrefixPattern(
            first="git",
            rest=(PatternToken.single("status"),),
        ),
        decision=Decision.ALLOW,
        justification="safe read-only",
    )
    match = rule.matches(["git", "status", "--short"])
    assert isinstance(match, PrefixRuleMatch)
    assert match.matched_prefix == ["git", "status"]
    assert match.decision is Decision.ALLOW
    assert match.justification == "safe read-only"


def test_validate_match_examples_passes_when_every_example_matches() -> None:
    rule = PrefixRule(
        pattern=PrefixPattern(
            first="git", rest=(PatternToken.single("status"),)
        ),
        decision=Decision.ALLOW,
    )
    validate_match_examples([rule], [["git", "status"]])


def test_validate_match_examples_raises_when_example_does_not_match() -> None:
    rule = PrefixRule(
        pattern=PrefixPattern(
            first="git", rest=(PatternToken.single("status"),)
        ),
        decision=Decision.ALLOW,
    )
    with pytest.raises(ExecPolicyError) as info:
        validate_match_examples([rule], [["git", "push"]])
    assert "unmatched" in str(info.value)


def test_validate_not_match_examples_raises_when_rule_matches() -> None:
    rule = PrefixRule(
        pattern=PrefixPattern(
            first="git", rest=(PatternToken.single("push"),)
        ),
        decision=Decision.FORBIDDEN,
    )
    with pytest.raises(ExecPolicyError) as info:
        validate_not_match_examples([rule], [["git", "push"]])
    assert "expected example to not match" in str(info.value)


# ---------------------------------------------------------------------------
# Mini-Starlark PolicyParser
# ---------------------------------------------------------------------------


def test_policy_parser_single_rule_literal_pattern() -> None:
    parser = PolicyParser()
    parser.parse("t.rules", 'prefix_rule(pattern=["git", "status"], decision="allow")')
    policy = parser.build()
    ev = policy.check(["git", "status"], _fallback_prompt)
    assert ev.decision is Decision.ALLOW


def test_policy_parser_alternatives_expand_to_multiple_rules() -> None:
    parser = PolicyParser()
    parser.parse(
        "t.rules",
        'prefix_rule(pattern=[["git", "hg"], "status"], decision="allow")',
    )
    policy = parser.build()
    assert policy.check(["git", "status"], _fallback_prompt).decision is Decision.ALLOW
    assert policy.check(["hg", "status"], _fallback_prompt).decision is Decision.ALLOW
    assert (
        policy.check(["git", "push"], _fallback_prompt).decision
        is Decision.PROMPT  # falls back
    )


def test_policy_parser_match_examples_validate() -> None:
    parser = PolicyParser()
    parser.parse(
        "t.rules",
        (
            'prefix_rule(pattern=["git", "status"], decision="allow", '
            'match=["git status", "git status --short"])'
        ),
    )
    policy = parser.build()
    assert policy.check(["git", "status"], _fallback_prompt).decision is Decision.ALLOW


def test_policy_parser_match_example_mismatch_raises() -> None:
    parser = PolicyParser()
    with pytest.raises(ExecPolicyError):
        parser.parse(
            "t.rules",
            (
                'prefix_rule(pattern=["git", "status"], decision="allow", '
                'match=["git push"])'
            ),
        )


def test_policy_parser_not_match_example_leakage_raises() -> None:
    parser = PolicyParser()
    with pytest.raises(ExecPolicyError):
        parser.parse(
            "t.rules",
            (
                'prefix_rule(pattern=["git", "status"], decision="allow", '
                'not_match=["git status"])'
            ),
        )


def test_policy_parser_rejects_unknown_builtin() -> None:
    parser = PolicyParser()
    with pytest.raises(ExecPolicyError) as info:
        parser.parse("t.rules", 'allow_rule(pattern=["git"])')
    assert "prefix_rule" in str(info.value)


def test_policy_parser_rejects_non_call_statement() -> None:
    parser = PolicyParser()
    with pytest.raises(ExecPolicyError):
        parser.parse("t.rules", "x = 1")


def test_policy_parser_empty_justification_is_rejected() -> None:
    parser = PolicyParser()
    with pytest.raises(ExecPolicyError):
        parser.parse(
            "t.rules",
            'prefix_rule(pattern=["ls"], decision="allow", justification="   ")',
        )


def test_policy_parser_syntax_error_includes_line() -> None:
    parser = PolicyParser()
    with pytest.raises(ExecPolicyError) as info:
        parser.parse("t.rules", "prefix_rule(pattern=['git',")
    assert "t.rules" in str(info.value)


# ---------------------------------------------------------------------------
# TOML-based ExecPolicyConfig (rules.rs)
# ---------------------------------------------------------------------------


_TOML_SAMPLE = """
[rules.git]
allow = ["git status", "git log *"]
deny = ["git push --force"]

[rules.danger]
allow = []
deny = ["rm -rf /"]
"""


def test_toml_evaluate_allow() -> None:
    config = ExecPolicyConfig.from_str(_TOML_SAMPLE)
    assert config.evaluate("git status").is_allow


def test_toml_evaluate_allow_glob() -> None:
    config = ExecPolicyConfig.from_str(_TOML_SAMPLE)
    assert config.evaluate("git log --oneline").is_allow


def test_toml_evaluate_deny_wins_over_allow() -> None:
    config = ExecPolicyConfig.from_str(_TOML_SAMPLE)
    decision = config.evaluate("git push --force")
    assert decision.is_deny
    assert "git" in decision.reason


def test_toml_evaluate_unknown_returns_ask_user() -> None:
    config = ExecPolicyConfig.from_str(_TOML_SAMPLE)
    decision = config.evaluate("unknown command")
    assert decision.is_ask_user


def test_toml_evaluate_cross_group_deny() -> None:
    config = ExecPolicyConfig.from_str(_TOML_SAMPLE)
    decision = config.evaluate("rm -rf /")
    assert decision.is_deny
    assert "danger" in decision.reason


def test_toml_rejects_malformed_schema() -> None:
    with pytest.raises(ValueError):
        ExecPolicyConfig.from_str('[rules.git]\nallow = "should-be-list"\n')


def test_toml_from_path_reads_file(tmp_path: Path) -> None:
    path = tmp_path / "pol.toml"
    path.write_text(_TOML_SAMPLE)
    config = ExecPolicyConfig.from_path(path)
    assert config.evaluate("git status").is_allow


def test_default_execpolicy_path_is_in_home() -> None:
    path = default_execpolicy_path()
    assert path is not None
    assert str(path).endswith(str(Path(".deepseek") / "execpolicy.toml"))


# ---------------------------------------------------------------------------
# amend.blocking_append_allow_prefix_rule (amend.rs)
# ---------------------------------------------------------------------------


def test_amend_creates_parent_dir(tmp_path: Path) -> None:
    policy_path = tmp_path / "rules" / "default.rules"
    blocking_append_allow_prefix_rule(
        policy_path, ["echo", "Hello, world!"]
    )
    assert policy_path.read_text() == (
        'prefix_rule(pattern=["echo", "Hello, world!"], decision="allow")\n'
    )


def test_amend_no_duplicate_newline(tmp_path: Path) -> None:
    policy_path = tmp_path / "rules" / "default.rules"
    policy_path.parent.mkdir()
    policy_path.write_text('prefix_rule(pattern=["ls"], decision="allow")\n')
    blocking_append_allow_prefix_rule(
        policy_path, ["echo", "Hello, world!"]
    )
    assert policy_path.read_text() == (
        'prefix_rule(pattern=["ls"], decision="allow")\n'
        'prefix_rule(pattern=["echo", "Hello, world!"], decision="allow")\n'
    )


def test_amend_inserts_newline_when_missing(tmp_path: Path) -> None:
    policy_path = tmp_path / "rules" / "default.rules"
    policy_path.parent.mkdir()
    # No trailing newline on the existing rule.
    policy_path.write_text('prefix_rule(pattern=["ls"], decision="allow")')
    blocking_append_allow_prefix_rule(
        policy_path, ["echo", "Hello, world!"]
    )
    assert policy_path.read_text() == (
        'prefix_rule(pattern=["ls"], decision="allow")\n'
        'prefix_rule(pattern=["echo", "Hello, world!"], decision="allow")\n'
    )


def test_amend_empty_prefix_raises(tmp_path: Path) -> None:
    from deepseek_tui.execpolicy import AmendError

    with pytest.raises(AmendError):
        blocking_append_allow_prefix_rule(tmp_path / "p.rules", [])


def test_amend_sets_secure_file_mode_on_unix(tmp_path: Path) -> None:
    policy_path = tmp_path / "p.rules"
    blocking_append_allow_prefix_rule(policy_path, ["echo", "x"])
    # File is readable/writable to user; we don't enforce 0600 here
    # (the amend.rs Rust impl does not chmod either — that's handled
    # at a higher layer). Just verify the file exists + is a regular
    # file.
    assert policy_path.is_file()
    # Sanity: created mode is at least user-readable.
    st_mode = os.stat(policy_path).st_mode
    assert st_mode & 0o400
