from types import SimpleNamespace

from project_mcp.config import load_config
from project_mcp.plugins.registry import configured_registry
from project_mcp.tools.project import get_project_overview


def _react_detected(root):
    frameworks = configured_registry(load_config(root)).frameworks()
    react = [f for f in frameworks if type(f).__name__ == "ReactFramework"]
    assert len(react) == 1
    return react[0].detect(SimpleNamespace(project_root=root))


def test_react_plugin_detects_a_package_json_that_declares_react(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')

    assert _react_detected(tmp_path)


def test_react_plugin_detects_a_source_file_that_imports_react(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.jsx").write_text(
        "import React from 'react';\n\nexport function App() {\n  return <div />;\n}\n"
    )

    assert _react_detected(tmp_path)


def test_react_plugin_does_not_detect_a_project_without_react(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"left-pad": "1.0.0"}}')
    (tmp_path / "index.js").write_text("export const x = 1;\n")

    assert not _react_detected(tmp_path)


def test_react_plugin_is_skipped_with_a_warning_when_javascript_is_disabled(tmp_path):
    (tmp_path / "package.json").write_text('{"dependencies": {"react": "^18.0.0"}}')
    (tmp_path / "mcpctl.toml").write_text('[plugins]\ndisabled = ["javascript"]\n')

    overview = get_project_overview(tmp_path)

    assert (
        "react plugin skipped: it requires the javascript plugin, which is not active"
        in overview["index_status"].get("warnings", [])
    )
    frameworks = configured_registry(load_config(tmp_path)).frameworks()
    assert "ReactFramework" not in [type(f).__name__ for f in frameworks]
