from app.models import Widget


def test_widget_has_name():
    assert Widget("gizmo").name == "gizmo"
