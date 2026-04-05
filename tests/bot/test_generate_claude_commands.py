"""Tests for scripts/generate_claude_commands.py."""
from pathlib import Path

import pytest

from scripts.generate_claude_commands import (
    extract_section,
    render_command,
    generate,
    build_claude_md_block,
    merge_claude_md,
    COMMANDS,
)

SAMPLE_LIFECYCLE = """\
# Feature Lifecycle

## Overview

A feature is a named unit of work. At most one is active per project.

## State Files

Feature index at `.claude/features.json`.
Per-feature at `.claude/features/<snake_name>.json`.

## Summary Format

Write a summary to `features/<name>.md` with sections: Goal, What Was Built,
Key Changes, Commits.

## Workflow

Start, complete, resume, discard.
"""


class TestExtractSection:
    def test_extracts_summary_format(self):
        result = extract_section(SAMPLE_LIFECYCLE, "Summary Format")
        assert "Write a summary" in result
        assert "Goal" in result

    def test_extracts_overview(self):
        result = extract_section(SAMPLE_LIFECYCLE, "Overview")
        assert "named unit of work" in result

    def test_missing_section_returns_empty(self):
        result = extract_section(SAMPLE_LIFECYCLE, "Nonexistent Section")
        assert result == ""

    def test_does_not_include_next_section(self):
        result = extract_section(SAMPLE_LIFECYCLE, "Overview")
        assert "State Files" not in result


class TestRenderCommand:
    def test_injects_summary_format(self):
        template = "Instructions here.\n\n## Summary Format\n\n{SUMMARY_FORMAT}\n"
        rendered = render_command(template, "Write the summary like THIS.")
        assert "Write the summary like THIS." in rendered

    def test_injects_snake_rule(self):
        template = "Rule: {SNAKE_RULE}"
        rendered = render_command(template, "")
        assert "my_feature" in rendered  # example in the rule

    def test_no_unresolved_placeholders(self):
        for name, template in COMMANDS.items():
            rendered = render_command(template, "Summary format text.")
            assert "{SUMMARY_FORMAT}" not in rendered, f"Unresolved placeholder in {name}"
            assert "{SNAKE_RULE}" not in rendered, f"Unresolved placeholder in {name}"


class TestGenerate:
    def test_generates_all_five_commands(self, tmp_path):
        lifecycle = tmp_path / "feature-lifecycle.md"
        lifecycle.write_text(SAMPLE_LIFECYCLE, encoding="utf-8")
        out_dir = tmp_path / "commands"

        written = generate(out_dir, lifecycle)

        assert len(written) == 5
        expected = {
            "start-feature.md",
            "complete-feature.md",
            "resume-feature.md",
            "list-features.md",
            "discard-feature.md",
        }
        assert {Path(p).name for p in written} == expected

    def test_output_files_contain_summary_format(self, tmp_path):
        lifecycle = tmp_path / "feature-lifecycle.md"
        lifecycle.write_text(SAMPLE_LIFECYCLE, encoding="utf-8")
        out_dir = tmp_path / "commands"
        generate(out_dir, lifecycle)

        for cmd in ("start-feature.md", "complete-feature.md", "resume-feature.md"):
            content = (out_dir / cmd).read_text()
            assert "Write a summary" in content, f"{cmd} missing summary format"

    def test_idempotent(self, tmp_path):
        lifecycle = tmp_path / "feature-lifecycle.md"
        lifecycle.write_text(SAMPLE_LIFECYCLE, encoding="utf-8")
        out_dir = tmp_path / "commands"

        generate(out_dir, lifecycle)
        first = {f.name: f.read_text() for f in out_dir.glob("*.md")}

        generate(out_dir, lifecycle)
        second = {f.name: f.read_text() for f in out_dir.glob("*.md")}

        assert first == second

    def test_creates_output_dir(self, tmp_path):
        lifecycle = tmp_path / "feature-lifecycle.md"
        lifecycle.write_text(SAMPLE_LIFECYCLE, encoding="utf-8")
        out_dir = tmp_path / "nested" / "commands"
        assert not out_dir.exists()

        generate(out_dir, lifecycle)

        assert out_dir.exists()

    def test_missing_lifecycle_doc_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            generate(tmp_path / "commands", tmp_path / "nonexistent.md")


class TestBuildClaudeMdBlock:
    def test_contains_markers(self):
        block = build_claude_md_block(SAMPLE_LIFECYCLE)
        assert "# BEGIN: feature-lifecycle" in block
        assert "# END: feature-lifecycle" in block

    def test_contains_overview(self):
        block = build_claude_md_block(SAMPLE_LIFECYCLE)
        assert "named unit of work" in block

    def test_contains_workflow(self):
        block = build_claude_md_block(SAMPLE_LIFECYCLE)
        assert "Start, complete, resume, discard" in block


class TestMergeClaudeMd:
    def test_creates_file_if_missing(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        merge_claude_md(path, "# BEGIN: feature-lifecycle\nblock\n# END: feature-lifecycle")
        assert path.exists()
        assert "block" in path.read_text()

    def test_appends_to_existing_file(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        path.write_text("# My existing instructions\n\nSome content.\n")
        merge_claude_md(path, "# BEGIN: feature-lifecycle\nblock\n# END: feature-lifecycle")
        content = path.read_text()
        assert "My existing instructions" in content
        assert "block" in content

    def test_replaces_existing_block(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        path.write_text(
            "# Custom stuff\n\n"
            "# BEGIN: feature-lifecycle\nold block content\n# END: feature-lifecycle\n\n"
            "# More custom stuff\n"
        )
        merge_claude_md(path, "# BEGIN: feature-lifecycle\nnew block\n# END: feature-lifecycle")
        content = path.read_text()
        assert "old block content" not in content
        assert "new block" in content
        assert "Custom stuff" in content
        assert "More custom stuff" in content

    def test_preserves_content_outside_block(self, tmp_path):
        path = tmp_path / "CLAUDE.md"
        path.write_text(
            "# Before\n\n"
            "# BEGIN: feature-lifecycle\nold\n# END: feature-lifecycle\n\n"
            "# After\n"
        )
        merge_claude_md(path, "# BEGIN: feature-lifecycle\nnew\n# END: feature-lifecycle")
        content = path.read_text()
        assert "# Before" in content
        assert "# After" in content
