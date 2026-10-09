from pathlib import Path

from project_mcp.config import load_config
from project_mcp.db import get_connection
from project_mcp.indexer import run_scan

FILES = {
    "shop/models.py": "from django.db import models\n\n\nclass Order(models.Model):\n    pass\n",
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


def test_a_urls_module_and_a_test_that_become_unreadable_do_not_abort_the_refresh(tmp_path, monkeypatch):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    conn = get_connection(tmp_path)
    run_scan(conn, tmp_path, load_config(tmp_path))
    (tmp_path / "shop" / "extra.py").write_text("X = 1\n")
    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name in {"urls.py", "test_views.py"}:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)

    run_scan(conn, tmp_path, load_config(tmp_path))

    extra = conn.execute("SELECT COUNT(*) FROM files WHERE path = 'shop/extra.py'").fetchone()[0]
    assert extra == 1
