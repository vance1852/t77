from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    Channel, ChannelOrder, CommissionRule, CommissionTier, Performance,
    PerformanceQuota, QuotaHold, SettlementStatement, Show, TicketOrder,
)
from .serializers import (
    ChannelOrderCreateSerializer, ChannelOrderSerializer,
    ChannelSerializer, CommissionRuleCreateSerializer, CommissionRuleSerializer,
    LoginSerializer, OrderCreateSerializer, OrderSerializer,
    PerformanceQuotaSerializer, PerformanceSerializer, QuotaAdjustSerializer,
    QuotaAllocateSerializer, QuotaHoldCreateSerializer, QuotaHoldSerializer,
    SettlementGenerateSerializer, SettlementStatementSerializer, ShowSerializer,
)
from .services import ChannelOrderService, QuotaService, SettlementService, StatsService


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = authenticate(username=s.validated_data["username"], password=s.validated_data["password"])
        if user is None:
            return Response({"detail": "用户名或密码错误"}, status=status.HTTP_401_UNAUTHORIZED)
        token = RefreshToken.for_user(user)
        return Response({"access_token": str(token.access_token), "token_type": "bearer"})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me(request):
    u = request.user
    return Response({"id": u.id, "username": u.username, "display_name": u.get_full_name() or "平台管理员"})


class ShowViewSet(viewsets.ModelViewSet):
    queryset = Show.objects.all().order_by("id")
    serializer_class = ShowSerializer


class PerformanceViewSet(viewsets.ModelViewSet):
    queryset = Performance.objects.select_related("show").all().order_by("start_at")
    serializer_class = PerformanceSerializer


class OrderViewSet(viewsets.ModelViewSet):
    queryset = TicketOrder.objects.select_related("performance", "performance__show").all().order_by("-id")
    http_method_names = ["get", "post"]

    def get_serializer_class(self):
        if self.action == "create":
            return OrderCreateSerializer
        return OrderSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        s = OrderCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        try:
            perf = Performance.objects.select_for_update().select_related("show").get(pk=data["performance"])
        except Performance.DoesNotExist:
            return Response({"detail": "场次不存在"}, status=status.HTTP_404_NOT_FOUND)

        try:
            direct_quota = PerformanceQuota.objects.select_for_update().get(
                performance=perf, channel__isnull=True
            )
        except PerformanceQuota.DoesNotExist:
            return Response({"detail": "该场次未分配直销配额"}, status=status.HTTP_400_BAD_REQUEST)

        if direct_quota.available < data["quantity"]:
            return Response(
                {"detail": f"直销配额不足：可用{direct_quota.available}张，需要{data['quantity']}张"},
                status=status.HTTP_409_CONFLICT
            )

        order = TicketOrder.objects.create(
            performance=perf,
            customer_name=data["customer_name"],
            phone=data.get("phone", ""),
            quantity=data["quantity"],
            amount=perf.price * data["quantity"],
            status="paid",
        )

        direct_quota.sold += data["quantity"]
        direct_quota.save(update_fields=["sold", "updated_at"])

        perf.sold_seats += data["quantity"]
        perf.save(update_fields=["sold_seats"])

        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def refund(self, request, pk=None):
        """直销退票。"""
        with transaction.atomic():
            order = TicketOrder.objects.select_for_update().get(pk=pk)
            if order.status == "refunded":
                return Response({"detail": "订单已退票"}, status=status.HTTP_400_BAD_REQUEST)
            if order.status != "paid":
                return Response({"detail": f"订单状态不允许退票：{order.status}"}, status=status.HTTP_400_BAD_REQUEST)

            perf = Performance.objects.select_for_update().get(pk=order.performance_id)
            perf.sold_seats = max(0, perf.sold_seats - order.quantity)
            perf.save(update_fields=["sold_seats"])

            try:
                direct_quota = PerformanceQuota.objects.select_for_update().get(
                    performance_id=order.performance_id, channel__isnull=True
                )
                direct_quota.sold = max(0, direct_quota.sold - order.quantity)
                direct_quota.save(update_fields=["sold", "updated_at"])
            except PerformanceQuota.DoesNotExist:
                pass

            order.status = "refunded"
            order.save(update_fields=["status"])

        return Response(OrderSerializer(order).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    show_total = Show.objects.count()
    show_on_sale = Show.objects.filter(status="on_sale").count()
    perf_total = Performance.objects.count()
    order_paid = TicketOrder.objects.filter(status="paid").count()
    sold = sum(p.sold_seats for p in Performance.objects.all())
    capacity = sum(p.total_seats for p in Performance.objects.all())
    return Response({
        "show_total": show_total,
        "show_on_sale": show_on_sale,
        "performance_total": perf_total,
        "order_paid": order_paid,
        "seats_sold": sold,
        "seats_capacity": capacity,
    })


class ChannelViewSet(viewsets.ModelViewSet):
    """渠道管理。"""
    queryset = Channel.objects.all().order_by("-id")
    serializer_class = ChannelSerializer


class CommissionRuleViewSet(viewsets.ModelViewSet):
    """佣金规则管理。"""
    queryset = CommissionRule.objects.select_related("channel").prefetch_related("tiers").all().order_by("-id")
    serializer_class = CommissionRuleSerializer

    def get_serializer_class(self):
        if self.action in ["create", "update", "partial_update"]:
            return CommissionRuleCreateSerializer
        return CommissionRuleSerializer

    def create(self, request, *args, **kwargs):
        s = CommissionRuleCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        with transaction.atomic():
            rule = CommissionRule.objects.create(
                channel_id=data["channel"],
                name=data["name"],
                rule_type=data["rule_type"],
                percentage_rate=data["percentage_rate"],
                fixed_amount=data["fixed_amount"],
                tier_base=data.get("tier_base", "quantity"),
                is_active=data.get("is_active", True),
                effective_from=data.get("effective_from"),
                effective_to=data.get("effective_to"),
            )

            tiers_data = data.get("tiers", [])
            for tier_data in tiers_data:
                CommissionTier.objects.create(
                    rule=rule,
                    min_value=tier_data["min_value"],
                    max_value=tier_data.get("max_value"),
                    tier_type=tier_data.get("tier_type", "percentage"),
                    rate=tier_data["rate"],
                )

        return Response(
            CommissionRuleSerializer(rule).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["get"], url_path="by-channel/(?P<channel_id>[^/.]+)")
    def by_channel(self, request, channel_id=None):
        """获取某渠道的佣金规则。"""
        rules = self.queryset.filter(channel_id=channel_id)
        return Response(CommissionRuleSerializer(rules, many=True).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        """启用佣金规则。"""
        rule = self.get_object()
        rule.is_active = True
        rule.save(update_fields=["is_active"])
        return Response(CommissionRuleSerializer(rule).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        """停用佣金规则。"""
        rule = self.get_object()
        rule.is_active = False
        rule.save(update_fields=["is_active"])
        return Response(CommissionRuleSerializer(rule).data)


class PerformanceQuotaViewSet(viewsets.ModelViewSet):
    """场次配额管理。"""
    queryset = PerformanceQuota.objects.select_related("channel", "performance", "performance__show").all().order_by("-id")
    serializer_class = PerformanceQuotaSerializer
    http_method_names = ["get", "post", "put", "patch"]

    def get_queryset(self):
        qs = super().get_queryset()
        performance_id = self.request.query_params.get("performance")
        channel_id = self.request.query_params.get("channel")
        if performance_id:
            qs = qs.filter(performance_id=performance_id)
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        return qs

    @action(detail=False, methods=["post"], url_path="allocate")
    def allocate(self, request):
        """分配配额。"""
        s = QuotaAllocateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        try:
            quota = QuotaService.allocate_quota(
                performance_id=data["performance"],
                channel_id=data.get("channel"),
                allocated_quantity=data["allocated"],
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PerformanceQuotaSerializer(quota).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="adjust")
    def adjust(self, request, pk=None):
        """调整配额（增减）。"""
        s = QuotaAdjustSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            quota = QuotaService.adjust_quota(
                quota_id=pk,
                delta=s.validated_data["delta"],
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PerformanceQuotaSerializer(quota).data)

    @action(detail=True, methods=["post"], url_path="reclaim")
    def reclaim(self, request, pk=None):
        """回收未使用配额。"""
        try:
            quota = QuotaService.reclaim_unused_quota(quota_id=pk)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(PerformanceQuotaSerializer(quota).data)

    @action(detail=False, methods=["get"], url_path="monitoring")
    def monitoring(self, request):
        """配额使用监控。"""
        performance_id = request.query_params.get("performance")
        try:
            pid = int(performance_id) if performance_id else None
        except (ValueError, TypeError):
            pid = None

        data = StatsService.get_quota_monitoring(performance_id=pid)
        return Response(data)


class QuotaHoldViewSet(viewsets.ModelViewSet):
    """配额软占用。"""
    queryset = QuotaHold.objects.select_related("channel", "performance").all().order_by("-created_at")
    serializer_class = QuotaHoldSerializer
    http_method_names = ["get", "post"]

    def get_queryset(self):
        qs = super().get_queryset()
        channel_id = self.request.query_params.get("channel")
        performance_id = self.request.query_params.get("performance")
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        if performance_id:
            qs = qs.filter(performance_id=performance_id)
        return qs

    def create(self, request, *args, **kwargs):
        """创建配额软占用。"""
        s = QuotaHoldCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        try:
            hold = QuotaService.hold_quota(
                channel_id=data["channel"],
                performance_id=data["performance"],
                quantity=data["quantity"],
                hold_minutes=data.get("hold_minutes", 15),
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(QuotaHoldSerializer(hold).data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="release")
    def release(self, request):
        """释放配额占用。"""
        hold_token = request.data.get("hold_token")
        if not hold_token:
            return Response({"detail": "hold_token必填"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            hold = QuotaService.release_quota_hold(hold_token=hold_token)
        except QuotaHold.DoesNotExist:
            return Response({"detail": "配额占用不存在"}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(QuotaHoldSerializer(hold).data)


class ChannelOrderViewSet(viewsets.ModelViewSet):
    """渠道订单管理。"""
    queryset = ChannelOrder.objects.select_related(
        "channel", "performance", "performance__show"
    ).all().order_by("-id")
    serializer_class = ChannelOrderSerializer
    http_method_names = ["get", "post"]

    def get_serializer_class(self):
        if self.action == "create":
            return ChannelOrderCreateSerializer
        return ChannelOrderSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        channel_id = self.request.query_params.get("channel")
        performance_id = self.request.query_params.get("performance")
        status_filter = self.request.query_params.get("status")
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        if performance_id:
            qs = qs.filter(performance_id=performance_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def create(self, request, *args, **kwargs):
        """创建渠道订单（占配额+扣库存）。"""
        s = ChannelOrderCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        try:
            order = ChannelOrderService.create_channel_order(
                channel_id=data["channel"],
                performance_id=data["performance"],
                quantity=data["quantity"],
                hold_token=data.get("hold_token"),
                channel_order_no=data.get("channel_order_no", ""),
                customer_name=data.get("customer_name", ""),
                customer_phone=data.get("customer_phone", ""),
            )
        except (ValueError, Channel.DoesNotExist, Performance.DoesNotExist, PerformanceQuota.DoesNotExist) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ChannelOrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def refund(self, request, pk=None):
        """渠道退票（冲销佣金+回退配额）。"""
        refund_quantity = request.data.get("refund_quantity")
        try:
            refund_qty = int(refund_quantity) if refund_quantity else None
        except (ValueError, TypeError):
            refund_qty = None

        try:
            order = ChannelOrderService.refund_channel_order(
                order_id=pk,
                refund_quantity=refund_qty,
            )
        except (ValueError, ChannelOrder.DoesNotExist) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(ChannelOrderSerializer(order).data)


class SettlementStatementViewSet(viewsets.ModelViewSet):
    """渠道结算单。"""
    queryset = SettlementStatement.objects.select_related(
        "channel"
    ).prefetch_related("items", "orders").all().order_by("-id")
    serializer_class = SettlementStatementSerializer
    http_method_names = ["get", "post"]

    def get_queryset(self):
        qs = super().get_queryset()
        channel_id = self.request.query_params.get("channel")
        status_filter = self.request.query_params.get("status")
        if channel_id:
            qs = qs.filter(channel_id=channel_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        """生成结算单。"""
        s = SettlementGenerateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data

        try:
            statement = SettlementService.generate_statement(
                channel_id=data["channel"],
                period_start=data["period_start"],
                period_end=data["period_end"],
                statement_no=data.get("statement_no") or None,
            )
        except (ValueError, Channel.DoesNotExist) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(SettlementStatementSerializer(statement).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        """确认结算单。"""
        try:
            statement = SettlementService.confirm_statement(statement_id=pk)
        except (ValueError, SettlementStatement.DoesNotExist) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(SettlementStatementSerializer(statement).data)

    @action(detail=True, methods=["post"])
    def settle(self, request, pk=None):
        """标记结算单已结算。"""
        try:
            statement = SettlementService.settle_statement(statement_id=pk)
        except (ValueError, SettlementStatement.DoesNotExist) as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(SettlementStatementSerializer(statement).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def channel_performance_ranking(request):
    """渠道业绩排行。"""
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")
    limit = request.query_params.get("limit", "10")
    try:
        limit = int(limit)
    except (ValueError, TypeError):
        limit = 10

    data = StatsService.get_channel_performance_ranking(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def commission_cost_stats(request):
    """佣金成本统计。"""
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")

    data = StatsService.get_commission_cost_stats(
        start_date=start_date,
        end_date=end_date,
    )
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def channel_sales_flow(request):
    """渠道售票流水（渠道订单列表，带筛选）。"""
    channel_id = request.query_params.get("channel")
    start_date = request.query_params.get("start_date")
    end_date = request.query_params.get("end_date")

    qs = ChannelOrder.objects.select_related(
        "channel", "performance", "performance__show"
    ).all().order_by("-created_at")

    if channel_id:
        qs = qs.filter(channel_id=channel_id)
    if start_date:
        qs = qs.filter(created_at__date__gte=start_date)
    if end_date:
        qs = qs.filter(created_at__date__lte=end_date)

    page = request.query_params.get("page", "1")
    page_size = request.query_params.get("page_size", "20")
    try:
        page = int(page)
        page_size = int(page_size)
    except (ValueError, TypeError):
        page, page_size = 1, 20

    start = (page - 1) * page_size
    end = start + page_size
    total = qs.count()
    items = qs[start:end]

    return Response({
        "total": total,
        "page": page,
        "page_size": page_size,
        "results": ChannelOrderSerializer(items, many=True).data,
    })
