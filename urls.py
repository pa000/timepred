from django.urls import path

from . import views

urlpatterns = [
    path("", views.index),
    path("vehicles", views.vehicles, name="vehicles"),
    path("details", views.details),
    path("history", views.history),
    path("stop", views.stop),
]
