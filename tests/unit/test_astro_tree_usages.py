import pytest

from project_mcp.plugins import treesitter
from project_mcp.plugins.astro import usages
from project_mcp.plugins.astro.tree_usages import default_imports

pytestmark = pytest.mark.skipif(
    treesitter.missing("typescript") is not None, reason="tree-sitter is not installed"
)


def test_default_imports_map_each_default_name_to_its_module():
    script = (
        "\nimport Card from '../components/Card.astro';\n"
        'import Layout, { title } from "../layouts/Layout.astro";\n'
        "import Other, * as ns from './other';\n"
        "import { Named } from './named';\n"
        "import * as all from './all';\n"
    )

    assert default_imports(script) == {
        "Card": "../components/Card.astro",
        "Layout": "../layouts/Layout.astro",
        "Other": "./other",
    }


def test_commented_out_and_type_only_imports_are_skipped():
    script = (
        "\n// import Ghost from './ghost';\n"
        "/* import Spirit from './spirit'; */\n"
        "import type Shape from './shape';\n"
        "const s = \"import Fake from './fake'\";\n"
    )

    assert default_imports(script) == {}


@pytest.mark.parametrize(
    "script",
    [
        "\nimport A from './a';\nimport B, { c } from './b';\n",
        "\nimport type T from './t';\nimport { x } from './x';\n",
    ],
)
def test_the_tree_and_regex_parsers_agree(script):
    assert default_imports(script) == usages.default_imports(script)
