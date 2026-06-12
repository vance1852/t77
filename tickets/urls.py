from django.http import JsonResponse
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    LoginView,
    OrderViewSet,
    PerformanceViewSet,
    ShowViewSet,
    dashboard_stats,
    me,
)


def health(_request):
    return JsonResponse({"status": "ok", "service": "show-ticketing-admin"})


router = DefaultRouter(trailing_slash=False)
router.register("shows", ShowViewSet)
router.register("performances", PerformanceViewSet)
router.register("orders", OrderViewSet)

urlpatterns = [
    path("health", health),
    path("auth/login", LoginView.as_view()),
    path("auth/me", me),
    path("dashboard/stats", dashboard_stats),
]

urlpatterns += router.urls
