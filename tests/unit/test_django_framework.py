from project_mcp.plugins.django.framework import _django_views_by_url_name

URLS = (
    "from django.urls import path\n\nfrom shop import views\n\n"
    "app_name = 'shop'\n"
    "urlpatterns = [path('<int:pk>/', views.order_detail, name='detail')]\n"
)


def test_a_urls_module_that_cannot_be_read_is_left_out(tmp_path):
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "views.py").write_text("def order_detail(request):\n    pass\n")
    (tmp_path / "shop" / "urls.py").write_text(URLS)
    path_to_file_id = {"shop/views.py": 1, "shop/urls.py": 2, "shop/gone/urls.py": 3}

    assert _django_views_by_url_name(tmp_path, path_to_file_id, []) == {
        "shop:detail": "shop.views.order_detail"
    }
