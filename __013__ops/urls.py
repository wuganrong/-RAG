"""生产运维数据接口 URL。"""

from django.urls import path

from . import views


urlpatterns = [
    path("usage/summary", views.usage_summary),
    path("usage/list", views.usage_list),
    path("cost/summary", views.cost_summary),
    path("audit/list", views.audit_list),
    path("quality/summary", views.quality_summary),
    path("health", views.health_check),
    path("safety/check", views.safety_check),
    path("alert/list", views.alert_list),
    path("alert/resolve", views.alert_resolve),
]
