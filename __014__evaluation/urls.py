from django.urls import path

from . import views


urlpatterns = [
    path("question/list", views.question_list),
    path("question/save", views.question_save),
    path("question/rm", views.question_rm),
    path("run", views.run_eval),
    path("result/list", views.result_list),
]
