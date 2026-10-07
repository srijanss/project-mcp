from project_mcp.plugins.javascript.analyzer import JavaScriptAnalyzer
from project_mcp.plugins.python.analyzer import PythonAnalyzer
from project_mcp.plugins.rust.analyzer import RustAnalyzer


def test_each_language_plugin_names_a_files_module_as_its_symbols_do():
    assert PythonAnalyzer().module_name("app/models.py") == "app.models"
    assert JavaScriptAnalyzer().module_name("src/ui/Button.tsx") == "src.ui.Button"
    assert RustAnalyzer().module_name("src/lib.rs") == "src.lib"


def test_context_packs_name_a_module_through_the_plugin_owning_its_file():
    from project_mcp.tools.context_packs import module_name_for

    assert module_name_for("app/views.js") == "app.views"
    assert module_name_for("app/models.py") == "app.models"
    assert module_name_for("docs/README.md") is None
