from types import SimpleNamespace

import pytest

from project_mcp.plugins.react.framework import ReactFramework


def _detect(project_root):
    return ReactFramework().detect(SimpleNamespace(project_root=project_root))


@pytest.mark.parametrize("section", ["dependencies", "devDependencies", "peerDependencies"])
def test_react_framework_detects_a_react_dependency(tmp_path, section):
    assert not _detect(tmp_path)

    (tmp_path / "package.json").write_text('{"dependencies": {"astro": "^4.0.0"}}')
    assert not _detect(tmp_path)

    (tmp_path / "package.json").write_text('{"%s": {"react": "^18.0.0"}}' % section)
    assert _detect(tmp_path)


@pytest.mark.parametrize(
    "source",
    [
        "import React from 'react';\n",
        'import { useState } from "react";\n',
        "const React = require('react');\n",
    ],
)
@pytest.mark.parametrize("name", ["App.jsx", "App.tsx", "app.js", "app.ts"])
def test_react_framework_detects_a_source_file_importing_react(tmp_path, name, source):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / name).write_text(source)

    assert _detect(tmp_path)


def test_react_framework_ignores_files_that_only_mention_react(tmp_path):
    (tmp_path / "a.js").write_text("import x from 'react-dom-server-utils';\n// import 'react'\n")
    (tmp_path / "notes.md").write_text("import React from 'react';\n")

    assert not _detect(tmp_path)


def test_react_framework_ignores_react_imports_inside_node_modules(tmp_path):
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "index.js").write_text("import React from 'react';\n")

    assert not _detect(tmp_path)


def test_react_framework_ignores_an_unreadable_package_json(tmp_path):
    (tmp_path / "package.json").write_text("{not json")

    assert not _detect(tmp_path)
