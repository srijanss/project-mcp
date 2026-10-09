from project_mcp.plugins.react.exports import default_export_name, export_aliases


def test_a_default_exported_function_or_class_declaration_names_the_default():
    assert default_export_name("export default function Main() {}\n") == "Main"
    assert default_export_name("export default async function Main() {}\n") == "Main"
    assert default_export_name("export default class Main extends Base {}\n") == "Main"


def test_a_default_exported_identifier_or_wrapped_identifier_names_the_default():
    assert default_export_name("const Main = () => null;\nexport default Main;\n") == "Main"
    assert default_export_name("export default memo(Main);\n") == "Main"
    assert default_export_name("export default React.forwardRef(Main)\n") == "Main"
    assert default_export_name("export default connect(a)(Main);\n") == "Main"


def test_an_export_list_alias_to_default_names_the_default():
    assert default_export_name("export { Inner as default, Other };\n") == "Inner"
    assert default_export_name("export {\n  Other,\n  Inner as default,\n};\n") == "Inner"
    assert default_export_name("export { Other };\n") is None


def test_commented_out_and_missing_default_exports_name_nothing():
    assert default_export_name("// export default function Old() {}\nexport const A = 1;\n") is None
    assert default_export_name("/* export { Old as default } */\n") is None


def test_export_aliases_map_each_renamed_export_to_its_local_name():
    source = """\
function Button() {}
function Card() {}
export { Button as Primary, Card, Card as Panel };
export { Button as default };
export { Other as Elsewhere } from './other';
// export { Card as Commented };
"""

    assert export_aliases(source) == {"Primary": "Button", "Panel": "Card"}
    assert export_aliases("export function Plain() {}\n") == {}
