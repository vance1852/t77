from django.urls import include, path

urlpatterns = [
    path("api/", include("tickets.urls")),
]
