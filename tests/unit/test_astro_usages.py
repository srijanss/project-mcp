from project_mcp.plugins.astro.usages import default_imports, rendered_tags


def test_default_imports_map_local_names_to_specifiers():
    script = (
        'import Layout from "../layouts/Layout.astro";\n'
        "import Card, { helper } from './Card.astro';\n"
        'import { named } from "./util";\n'
        'import * as UI from "./ui";\n'
        'import "./side-effect.css";\n'
    )

    assert default_imports(script) == {
        "Layout": "../layouts/Layout.astro",
        "Card": "./Card.astro",
    }


def test_rendered_tags_are_the_capitalised_component_tags_in_the_template():
    template = '<Layout><Card /><Card title="x"></Card><div><Icon/></div><slot /></Layout>'

    assert rendered_tags(template) == {"Layout", "Card", "Icon"}


def test_rendered_tags_ignore_html_elements_and_namespaced_or_member_tags():
    assert rendered_tags("<div><span /><ui.Button /><Foo.Bar /></div>") == set()


def test_default_imports_on_the_same_line_are_all_found():
    script = "import A from './A.astro'; import B from './B.astro';\nimport C from './C.astro'"

    assert default_imports(script) == {"A": "./A.astro", "B": "./B.astro", "C": "./C.astro"}


def test_type_only_and_member_text_are_not_default_imports():
    script = "import type Props from './types';\nconst x = obj.import Foo from 'x';"

    assert default_imports(script) == {}

