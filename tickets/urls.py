from django.http import JsonResponse
from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    ChannelOrderViewSet, ChannelViewSet, CommissionRuleViewSet,
    LoginView, OrderViewSet, PerformanceQuotaViewSet, PerformanceViewSet,
    QuotaHoldViewSet, SettlementStatementViewSet, ShowViewSet,
    channel_performance_ranking, channel_sales_flow, commission_cost_stats,
    dashboard_stats, me,
)


def health(_request):
    return JsonResponse({"status": "ok", "service": "show-ticketing-admin"})


router = DefaultRouter(trailing_slash=False)
router.register("shows", ShowViewSet)
router.register("performances", PerformanceViewSet)
router.register("orders", OrderViewSet)
router.register("channels", ChannelViewSet)
router.register("commission-rules", CommissionRuleViewSet, basename="commissionrule")
router.register("quotas", PerformanceQuotaViewSet, basename="quota")
router.register("quota-holds", QuotaHoldViewSet, basename="quotahold")
router.register("channel-orders", ChannelOrderViewSet, basename="channelorder")
router.register("settlements", SettlementStatementViewSet, basename="settlement")

urlpatterns = [
    path("health", health),
    path("auth/login", LoginView.as_view()),
    path("auth/me", me),
    path("dashboard/stats", dashboard_stats),
    path("stats/channel-ranking", channel_performance_ranking),
    path("stats/commission-cost", commission_cost_stats),
    path("stats/channel-sales-flow", channel_sales_flow),
]

urlpatterns += router.urls
