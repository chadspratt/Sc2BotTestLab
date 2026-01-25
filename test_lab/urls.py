from django.urls import path
from . import views

urlpatterns = [
    path('', views.match_list, name='match_list'),
    path('trigger-tests/', views.trigger_tests, name='trigger_tests'),
    path('replay/<int:match_id>/', views.serve_replay, name='serve_replay'),
    path('log/<int:match_id>/', views.serve_log, name='serve_log'),
]
