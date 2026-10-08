from project_mcp.plugins.astro.framework import AstroFramework

PAGE = "src/pages/index.astro"
SOURCE = (
    '---\nimport Layout from "../layouts/Layout.ts";\n'
    'export function title() { return "x"; }\n---\n<h1>hi</h1>\n'
)


def _symbols(analysis):
    return {(s["qualified_name"], s["kind"]): s["start_line"] for s in analysis.symbols}


def test_astro_analysis_parses_the_frontmatter_keeping_file_line_numbers():
    analysis = AstroFramework().analyze(PAGE, SOURCE)

    symbols = _symbols(analysis)
    assert ("src.pages.index", "module") in symbols
    (title,) = [line for (name, _), line in symbols.items() if name.endswith(".title")]
    assert title == 3
    assert analysis.imports == ["../layouts/Layout.ts"]


def test_astro_module_symbol_spans_the_whole_file():
    analysis = AstroFramework().analyze(PAGE, SOURCE)

    (module,) = [s for s in analysis.symbols if s["kind"] == "module"]
    assert (module["start_line"], module["end_line"]) == (1, 5)


def test_astro_file_without_frontmatter_has_only_its_module_and_component_symbols():
    analysis = AstroFramework().analyze("src/components/Card.astro", "<div />\n")

    assert [s["kind"] for s in analysis.symbols] == ["module", "component"]
    assert analysis.imports == []


def test_astro_module_name_drops_the_astro_suffix():
    assert AstroFramework().module_name(PAGE) == "src.pages.index"


def test_crlf_line_endings_keep_frontmatter_symbols_and_line_numbers():
    source = "---\r\nimport A from './A.astro';\r\nexport function f() {}\r\n---\r\n<A />\r\n"

    analysis = AstroFramework().analyze("src/pages/index.astro", source)

    assert analysis.imports == ["./A.astro"]
    assert {s["name"]: s["start_line"] for s in analysis.symbols}["f"] == 3
    (component,) = [s for s in analysis.symbols if s["kind"] == "component"]
    assert component["end_line"] == 5


def test_an_unterminated_fence_leaves_the_whole_file_as_template():
    source = "---\nimport A from './A.astro';\n<A />\n"

    analysis = AstroFramework().analyze("src/pages/index.astro", source)

    assert analysis.imports == []
    assert [s["kind"] for s in analysis.symbols] == ["module", "component"]
