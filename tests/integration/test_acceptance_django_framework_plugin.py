import json

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan
from project_mcp.plugins.python.descriptor import DESCRIPTOR as python
from project_mcp.plugins.registry import PluginRegistry, builtin_registry

FILES = {
    "shop/models.py": (
        "from django.db import models\n\n\nclass Order(models.Model):\n    pass\n"
    ),
    "shop/views.py": "def order_detail(request):\n    pass\n",
    "shop/urls.py": (
        "from django.urls import path\n\nfrom shop import views\n\n"
        "app_name = 'shop'\n"
        "urlpatterns = [path('<int:pk>/', views.order_detail, name='detail')]\n"
    ),
    "tests/test_views.py": (
        "from django.urls import reverse\n\n\n"
        "def test_detail(client):\n    client.get(reverse('shop:detail', args=[1]))\n"
    ),
}


def _scan(tmp_path, registry):
    for path, source in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(source)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path), registry=registry)
    framework_kinds = {
        name: json.loads(metadata or "{}").get("framework_kind")
        for name, metadata in conn.execute(
            "SELECT qualified_name, metadata_json FROM symbols"
            " WHERE qualified_name = 'shop.models.Order'"
        )
    }
    url_reverses = conn.execute(
        """SELECT COUNT(*) FROM relationships WHERE evidence_json = '["url_reverse"]'"""
    ).fetchone()[0]
    return framework_kinds, url_reverses


def test_django_enrichment_runs_as_a_framework_plugin(tmp_path):
    assert _scan(tmp_path / "with", builtin_registry()) == (
        {"shop.models.Order": "django_model"},
        1,
    )


def test_without_the_django_plugin_python_files_get_no_django_enrichment(tmp_path):
    registry = PluginRegistry()
    registry.register(python)

    assert _scan(tmp_path / "without", registry) == ({"shop.models.Order": None}, 0)
