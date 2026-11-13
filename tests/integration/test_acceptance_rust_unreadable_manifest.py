import pytest

from project_mcp.tools.tests import get_tests_for

LIB = """\
pub fn add() {}

#[cfg(test)]
mod tests {
    #[test]
    fn adds() {
        crate::add();
    }
}
"""

MANIFESTS = {
    "invalid utf-8": b'[package]\nname = "caf\xe9"\n',
    "malformed toml": b"[package\nname = ",
    "no package": b'[workspace]\nmembers = []\n',
    "name not a string": b"[package]\nname = 3\n",
    "missing": None,
}


@pytest.mark.parametrize("manifest", MANIFESTS.values(), ids=MANIFESTS.keys())
def test_a_crate_whose_manifest_cannot_be_read_still_links_its_tests(tmp_path, manifest):
    if manifest is not None:
        (tmp_path / "Cargo.toml").write_bytes(manifest)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "lib.rs").write_text(LIB)

    assert [row.get("tests") for row in get_tests_for(tmp_path, "src.lib.add")] == [["src.lib.tests.adds"]]
