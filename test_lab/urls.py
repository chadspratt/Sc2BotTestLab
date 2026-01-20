from django.urls import path
from . import views

urlpatterns = [
    path('', views.match_list, name='match_list'),
    path('trigger-tests/', views.trigger_tests, name='trigger_tests'),
]
