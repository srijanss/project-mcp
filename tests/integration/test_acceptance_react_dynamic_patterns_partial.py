import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.tools.symbols import get_dependents

FILES = {
    "package.json": '{"dependencies": {"react": "^18.0.0", "react-router-dom": "^6.0.0"}}',
    "src/Lazy.tsx": "export default function Lazy() {\n  return <p />;\n}\n",
    "src/Alpha.tsx": "export function Alpha() {\n  return <a />;\n}\n",
    "src/Beta.tsx": "export function Beta() {\n  return <b />;\n}\n",
    "src/Lazily.tsx": (
        "import React from 'react';\n\n"
        "const Lazy = React.lazy(() => import('./Lazy'));\n\n"
        "export function Lazily() {\n  return <Lazy />;\n}\n"
    ),
    "src/Picker.tsx": (
        "import { Alpha } from './Alpha';\n"
        "import { Beta } from './Beta';\n\n"
        "export function Picker({ flag }) {\n"
        "  const Chosen = flag ? Alpha : Beta;\n"
        "  return <Chosen />;\n"
        "}\n"
    ),
    "src/Dynamic.tsx": (
        "export function Dynamic({ routeProps }) {\n"
        "  return <Route {...routeProps} />;\n"
        "}\n"
    ),
    "src/Sure.tsx": (
        "import { Alpha } from './Alpha';\n\n"
        "export function Sure() {\n  return <Alpha />;\n}\n"
    ),
}


def _scan(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    return {
        name: json.loads(meta or "{}")
        for name, meta in conn.execute(
            "SELECT name, metadata_json FROM symbols WHERE kind = 'component'"
        )
    }


def test_a_lazy_import_is_a_low_confidence_renders_and_marks_the_component_partial(tmp_path):
    components = _scan(tmp_path)

    assert get_dependents(tmp_path, "src.Lazy.Lazy") == [
        {"source": "src.Lazily.Lazily", "relationship_type": "renders", "confidence": "low"}
    ]
    assert components["Lazily"]["partial"] is True


def test_a_computed_component_variable_links_every_candidate_with_low_confidence(tmp_path):
    components = _scan(tmp_path)

    dependents = get_dependents(tmp_path, "src.Beta.Beta")
    assert dependents == [
        {"source": "src.Picker.Picker", "relationship_type": "renders", "confidence": "low"}
    ]
    assert components["Picker"]["partial"] is True


def test_definite_usages_stay_high_confidence_and_unmarked(tmp_path):
    components = _scan(tmp_path)

    assert {"source": "src.Sure.Sure", "relationship_type": "renders", "confidence": "high"} in (
        get_dependents(tmp_path, "src.Alpha.Alpha")
    )
    assert "partial" not in components["Sure"]


def test_a_spread_route_config_is_marked_partial_without_any_relationship(tmp_path):
    components = _scan(tmp_path)

    assert components["Dynamic"]["partial"] is True
    assert get_dependents(tmp_path, "src.Dynamic.Dynamic") == []
