import json

from project_mcp.tools.dependencies import list_dependencies

LOCK = {
    "lockfileVersion": 3,
    "packages": {
        "": {},
        "node_modules/left-pad": {"version": "2.0.0"},
        "node_modules/@scope/ui": {"version": "3.1.0"},
        "node_modules/other": {"version": "1.0.0"},
        "node_modules/other/node_modules/left-pad": {"version": "1.5.0"},
        "node_modules/other/node_modules/@scope/ui": {"version": "0.9.0"},
    },
}


def test_a_nested_transitive_copy_does_not_replace_the_resolved_version_of_a_direct_dependency(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"left-pad": "^2.0.0", "@scope/ui": "^3.0.0"}})
    )
    (tmp_path / "package-lock.json").write_text(json.dumps(LOCK))

    versions = {d["name"]: d["version"] for d in list_dependencies(tmp_path, "npm")}

    assert versions == {"left-pad": "2.0.0", "@scope/ui": "3.1.0"}
