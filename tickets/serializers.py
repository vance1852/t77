from rest_framework import serializers

from .models import (
    Channel, ChannelOrder, CommissionRule, CommissionTier, Performance,
    PerformanceQuota, QuotaHold, SettlementItem, SettlementStatement,
    Show, TicketOrder,
)


class ShowSerializer(serializers.ModelSerializer):
    class Meta:
        model = Show
        fields = ["id", "title", "troupe", "genre", "status", "created_at"]
        read_only_fields = ["id", "created_at"]


class PerformanceSerializer(serializers.ModelSerializer):
    show_title = serializers.CharField(source="show.title", read_only=True)
    remaining_seats = serializers.SerializerMethodField()

    class Meta:
        model = Performance
        fields = [
            "id", "show", "show_title", "hall", "start_at",
            "total_seats", "sold_seats", "remaining_seats", "price", "created_at",
        ]
        read_only_fields = ["id", "sold_seats", "created_at"]

    def get_remaining_seats(self, obj):
        return obj.total_seats - obj.sold_seats


class OrderSerializer(serializers.ModelSerializer):
    show_title = serializers.CharField(source="performance.show.title", read_only=True)

    class Meta:
        model = TicketOrder
        fields = [
            "id", "performance", "show_title", "customer_name", "phone",
            "quantity", "amount", "status", "created_at",
        ]
        read_only_fields = ["id", "amount", "status", "created_at"]


class OrderCreateSerializer(serializers.Serializer):
    performance = serializers.IntegerField()
    customer_name = serializers.CharField(max_length=64)
    phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    quantity = serializers.IntegerField(min_value=1, max_value=10)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class ChannelSerializer(serializers.ModelSerializer):
    channel_type_label = serializers.CharField(source="get_channel_type_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    settlement_method_label = serializers.CharField(source="get_settlement_method_display", read_only=True)
    settlement_cycle_label = serializers.CharField(source="get_settlement_cycle_display", read_only=True)

    class Meta:
        model = Channel
        fields = [
            "id", "name", "code", "channel_type", "channel_type_label",
            "contact_person", "contact_phone", "contact_email",
            "settlement_method", "settlement_method_label",
            "settlement_cycle", "settlement_cycle_label",
            "settlement_account", "status", "status_label",
            "remark", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class CommissionTierSerializer(serializers.ModelSerializer):
    tier_type_label = serializers.CharField(source="get_tier_type_display", read_only=True)

    class Meta:
        model = CommissionTier
        fields = [
            "id", "min_value", "max_value", "tier_type", "tier_type_label", "rate", "created_at"]
        read_only_fields = ["id", "created_at"]


class CommissionRuleSerializer(serializers.ModelSerializer):
    rule_type_label = serializers.CharField(source="get_rule_type_display", read_only=True)
    tier_base_label = serializers.CharField(source="get_tier_base_display", read_only=True)
    tiers = CommissionTierSerializer(many=True, read_only=True)

    class Meta:
        model = CommissionRule
        fields = [
            "id", "channel", "name", "rule_type", "rule_type_label",
            "percentage_rate", "fixed_amount", "tier_base", "tier_base_label",
            "is_active", "effective_from", "effective_to",
            "tiers", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class CommissionRuleCreateSerializer(serializers.Serializer):
    channel = serializers.IntegerField()
    name = serializers.CharField(max_length=128)
    rule_type = serializers.ChoiceField(choices=CommissionRule.TYPE_CHOICES)
    percentage_rate = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=0)
    fixed_amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, default=0)
    tier_base = serializers.ChoiceField(choices=CommissionRule.TIER_BASE_CHOICES, required=False, default="quantity")
    is_active = serializers.BooleanField(required=False, default=True)
    effective_from = serializers.DateField(required=False, allow_null=True, default=None)
    effective_to = serializers.DateField(required=False, allow_null=True, default=None)
    tiers = CommissionTierSerializer(many=True, required=False, default=list)


class PerformanceQuotaSerializer(serializers.ModelSerializer):
    channel_name = serializers.SerializerMethodField()
    available = serializers.SerializerMethodField()
    sell_rate = serializers.SerializerMethodField()
    performance_title = serializers.CharField(source="performance.show.title", read_only=True)

    class Meta:
        model = PerformanceQuota
        fields = [
            "id", "performance", "performance_title", "channel", "channel_name",
            "allocated", "sold", "held", "available", "sell_rate",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "sold", "held", "created_at", "updated_at"]

    def get_channel_name(self, obj):
        return obj.channel_name

    def get_available(self, obj):
        return obj.available

    def get_sell_rate(self, obj):
        if obj.allocated > 0:
            return round(obj.sold / obj.allocated * 100, 2)
        return 0


class QuotaHoldSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = QuotaHold
        fields = [
            "id", "quota", "channel", "performance", "quantity",
            "hold_token", "status", "status_label", "expires_at",
            "is_expired", "created_at",
        ]
        read_only_fields = [
            "id", "hold_token", "status", "expires_at", "created_at",
        ]


class ChannelOrderSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    channel_name = serializers.CharField(source="channel.name", read_only=True)
    show_title = serializers.CharField(source="performance.show.title", read_only=True)

    class Meta:
        model = ChannelOrder
        fields = [
            "id", "channel", "channel_name", "performance", "show_title",
            "channel_order_no", "customer_name", "customer_phone",
            "quantity", "unit_price", "ticket_amount", "commission_amount",
            "status", "status_label", "is_settled", "created_at", "refunded_at",
        ]
        read_only_fields = [
            "id", "ticket_amount", "commission_amount", "status",
            "is_settled", "created_at", "refunded_at",
        ]


class ChannelOrderCreateSerializer(serializers.Serializer):
    channel = serializers.IntegerField()
    performance = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=100)
    hold_token = serializers.UUIDField(required=False, allow_null=True, default=None)
    channel_order_no = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    customer_name = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    customer_phone = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")


class QuotaHoldCreateSerializer(serializers.Serializer):
    channel = serializers.IntegerField()
    performance = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=100)
    hold_minutes = serializers.IntegerField(min_value=1, max_value=1440, required=False, default=15)


class QuotaAllocateSerializer(serializers.Serializer):
    performance = serializers.IntegerField()
    channel = serializers.IntegerField(required=False, allow_null=True, default=None)
    allocated = serializers.IntegerField(min_value=0)


class QuotaAdjustSerializer(serializers.Serializer):
    delta = serializers.IntegerField()


class SettlementItemSerializer(serializers.ModelSerializer):
    item_type_label = serializers.CharField(source="get_item_type_display", read_only=True)

    class Meta:
        model = SettlementItem
        fields = [
            "id", "statement", "order", "item_type", "item_type_label",
            "quantity", "ticket_amount", "commission_amount", "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class SettlementStatementSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    channel_name = serializers.CharField(source="channel.name", read_only=True)
    items = SettlementItemSerializer(many=True, read_only=True)

    class Meta:
        model = SettlementStatement
        fields = [
            "id", "channel", "channel_name", "statement_no",
            "period_start", "period_end",
            "total_tickets", "total_ticket_amount", "total_commission",
            "refund_tickets", "refund_ticket_amount", "refund_commission",
            "net_settlement_amount",
            "status", "status_label", "remark",
            "generated_at", "confirmed_at", "settled_at",
            "items",
        ]
        read_only_fields = [
            "id", "statement_no", "total_tickets", "total_ticket_amount",
            "total_commission", "refund_tickets", "refund_ticket_amount",
            "refund_commission", "net_settlement_amount",
            "status", "generated_at", "confirmed_at", "settled_at", "items",
        ]


class SettlementGenerateSerializer(serializers.Serializer):
    channel = serializers.IntegerField()
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    statement_no = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")


class ChannelPerformanceRankingSerializer(serializers.Serializer):
    channel_id = serializers.IntegerField()
    channel__name = serializers.CharField()
    total_orders = serializers.IntegerField()
    total_tickets = serializers.IntegerField()
    total_ticket_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_commission = serializers.DecimalField(max_digits=14, decimal_places=2)
