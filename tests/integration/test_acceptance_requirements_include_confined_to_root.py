from project_mcp.tools.dependencies import list_dependencies


def test_requirements_includes_outside_the_project_root_are_never_read(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("TOKEN=abc123notreal\n")
    (project / "requirements.txt").write_text(
        f"-r {outside}\n-r ../outside.txt\n-r base.txt\nrequests>=2\n"
    )
    (project / "base.txt").write_text("httpx>=0.27\n")

    names = sorted(d["name"] for d in list_dependencies(project))

    assert names == ["httpx", "requests"]
