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


def test_astro_file_without_frontmatter_is_just_a_module_symbol():
    analysis = AstroFramework().analyze("src/components/Card.astro", "<div />\n")

    assert [s["kind"] for s in analysis.symbols] == ["module"]
    assert analysis.imports == []


def test_astro_module_name_drops_the_astro_suffix():
    assert AstroFramework().module_name(PAGE) == "src.pages.index"
