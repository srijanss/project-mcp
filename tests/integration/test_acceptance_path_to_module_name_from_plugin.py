from project_mcp.tools.context_packs import get_context_for_architecture


def test_architecture_context_infers_structure_of_non_python_modules(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "util.js").write_text("export function helper() {}\n")
    (tmp_path / "app" / "views.js").write_text("import { helper } from './util';\n")

    context = get_context_for_architecture(tmp_path, "views")

    assert context["structure"]["inferred_structure"] == [
        {"module": "app/views.js", "depends_on": ["app/util.js"]}
    ]
