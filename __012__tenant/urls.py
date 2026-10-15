"""租户与用户角色 URL。"""

from django.urls import path

from . import views


urlpatterns = [
    path("list", views.tenant_list),
    path("save", views.tenant_save),
    path("rm", views.tenant_rm),
    path("user/list", views.user_role_list),
    path("user/save", views.user_role_save),
    path("user/rm", views.user_role_rm),
    path("quota/get", views.quota_get),
    path("quota/save", views.quota_save),
]
