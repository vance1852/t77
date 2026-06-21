import uuid
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone


class Show(models.Model):
    """演出剧目。"""

    GENRE_CHOICES = [
        ("concert", "演唱会"),
        ("drama", "话剧"),
        ("musical", "音乐剧"),
        ("opera", "戏曲"),
        ("other", "其他"),
    ]
    STATUS_CHOICES = [
        ("on_sale", "售票中"),
        ("upcoming", "待开票"),
        ("ended", "已结束"),
    ]

    title = models.CharField(max_length=128)
    troupe = models.CharField(max_length=128, blank=True, default="")
    genre = models.CharField(max_length=16, choices=GENRE_CHOICES, default="concert")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="upcoming")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "shows"


class Performance(models.Model):
    """场次。"""

    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name="performances")
    hall = models.CharField(max_length=64, default="")
    start_at = models.DateTimeField()
    total_seats = models.IntegerField(default=0)
    sold_seats = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "performances"

    @property
    def remaining_seats(self):
        return self.total_seats - self.sold_seats


class TicketOrder(models.Model):
    """购票订单（直销订单）。"""

    STATUS_CHOICES = [
        ("paid", "已支付"),
        ("cancelled", "已取消"),
        ("refunded", "已退票"),
    ]

    performance = models.ForeignKey(Performance, on_delete=models.CASCADE, related_name="orders")
    customer_name = models.CharField(max_length=64)
    phone = models.CharField(max_length=32, blank=True, default="")
    quantity = models.IntegerField(default=1)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="paid")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ticket_orders"


class Channel(models.Model):
    """分销渠道。"""

    TYPE_CHOICES = [
        ("agent", "代理商"),
        ("platform", "平台"),
        ("group", "团购"),
    ]
    SETTLEMENT_METHOD_CHOICES = [
        ("bank_transfer", "银行转账"),
        ("alipay", "支付宝"),
        ("wechat", "微信支付"),
    ]
    SETTLEMENT_CYCLE_CHOICES = [
        ("daily", "日结"),
        ("weekly", "周结"),
        ("monthly", "月结"),
    ]
    STATUS_CHOICES = [
        ("active", "启用"),
        ("inactive", "停用"),
    ]

    name = models.CharField(max_length=128)
    code = models.CharField(max_length=32, unique=True)
    channel_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default="agent")
    contact_person = models.CharField(max_length=64, blank=True, default="")
    contact_phone = models.CharField(max_length=32, blank=True, default="")
    contact_email = models.CharField(max_length=128, blank=True, default="")
    settlement_method = models.CharField(
        max_length=16, choices=SETTLEMENT_METHOD_CHOICES, default="bank_transfer"
    )
    settlement_cycle = models.CharField(
        max_length=16, choices=SETTLEMENT_CYCLE_CHOICES, default="monthly"
    )
    settlement_account = models.CharField(max_length=128, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    remark = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "channels"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.name}({self.code})"


class CommissionRule(models.Model):
    """佣金规则。"""

    TYPE_CHOICES = [
        ("percentage", "按比例"),
        ("fixed", "按张固定"),
        ("tiered", "阶梯佣金"),
    ]
    TIER_BASE_CHOICES = [
        ("quantity", "按销量阶梯"),
        ("amount", "按金额阶梯"),
    ]

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="commission_rules")
    name = models.CharField(max_length=128)
    rule_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default="percentage")
    percentage_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="百分比佣金，如10表示10%"
    )
    fixed_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text="固定金额佣金，元/张"
    )
    tier_base = models.CharField(
        max_length=16, choices=TIER_BASE_CHOICES, default="quantity",
        help_text="阶梯佣金的基准"
    )
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "commission_rules"
        ordering = ["-id"]

    def calculate_commission(self, quantity, unit_price):
        """根据规则计算佣金。"""
        total_amount = Decimal(unit_price) * Decimal(quantity)

        if self.rule_type == "percentage":
            return total_amount * self.percentage_rate / Decimal("100")
        elif self.rule_type == "fixed":
            return self.fixed_amount * Decimal(quantity)
        elif self.rule_type == "tiered":
            return self._calculate_tiered_commission(quantity, total_amount)
        return Decimal("0")

    def _calculate_tiered_commission(self, quantity, total_amount):
        """计算阶梯佣金。"""
        tiers = self.tiers.order_by("min_value")
        if not tiers.exists():
            return Decimal("0")

        base_value = quantity if self.tier_base == "quantity" else float(total_amount)
        applicable_tier = None

        for tier in tiers:
            if tier.max_value is None:
                if base_value >= tier.min_value:
                    applicable_tier = tier
            else:
                if tier.min_value <= base_value <= tier.max_value:
                    applicable_tier = tier
                    break

        if applicable_tier is None:
            return Decimal("0")

        if applicable_tier.tier_type == "percentage":
            return total_amount * applicable_tier.rate / Decimal("100")
        else:
            return applicable_tier.rate * Decimal(quantity)


class CommissionTier(models.Model):
    """阶梯佣金档位。"""

    TIER_TYPE_CHOICES = [
        ("percentage", "比例"),
        ("fixed", "固定金额"),
    ]

    rule = models.ForeignKey(CommissionRule, on_delete=models.CASCADE, related_name="tiers")
    min_value = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="阶梯下限（含）")
    max_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, help_text="阶梯上限（含），为空表示无上限")
    tier_type = models.CharField(max_length=16, choices=TIER_TYPE_CHOICES, default="percentage")
    rate = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="比例或固定金额")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "commission_tiers"
        ordering = ["min_value"]


class PerformanceQuota(models.Model):
    """场次库存配额。"""

    performance = models.ForeignKey(
        Performance, on_delete=models.CASCADE, related_name="quotas"
    )
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="quotas", null=True, blank=True,
        help_text="为空表示直销配额"
    )
    allocated = models.IntegerField(default=0, help_text="分配的库存额度")
    sold = models.IntegerField(default=0, help_text="已售出数量")
    held = models.IntegerField(default=0, help_text="软占用数量")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "performance_quotas"
        unique_together = [["performance", "channel"]]
        ordering = ["-id"]

    @property
    def available(self):
        """可用配额 = 分配 - 已售 - 占用。"""
        return self.allocated - self.sold - self.held

    @property
    def channel_name(self):
        if self.channel:
            return self.channel.name
        return "直销"


class QuotaHold(models.Model):
    """配额软占用记录。"""

    STATUS_CHOICES = [
        ("active", "占用中"),
        ("released", "已释放"),
        ("consumed", "已消费"),
    ]

    quota = models.ForeignKey(PerformanceQuota, on_delete=models.CASCADE, related_name="holds")
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="quota_holds")
    performance = models.ForeignKey(Performance, on_delete=models.CASCADE, related_name="quota_holds")
    quantity = models.IntegerField(default=0)
    hold_token = models.UUIDField(default=uuid.uuid4, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "quota_holds"
        ordering = ["-created_at"]

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at


class ChannelOrder(models.Model):
    """渠道订单。"""

    STATUS_CHOICES = [
        ("paid", "已支付"),
        ("partially_refunded", "部分退票"),
        ("refunded", "已退票"),
        ("cancelled", "已取消"),
    ]

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="orders")
    performance = models.ForeignKey(Performance, on_delete=models.CASCADE, related_name="channel_orders")
    channel_order_no = models.CharField(max_length=128, blank=True, default="")
    customer_name = models.CharField(max_length=64, blank=True, default="")
    customer_phone = models.CharField(max_length=32, blank=True, default="")
    quantity = models.IntegerField(default=0)
    refunded_quantity = models.IntegerField(default=0, help_text="累计已退票数量")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    ticket_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default="paid")
    hold_token = models.UUIDField(null=True, blank=True)
    is_settled = models.BooleanField(default=False, help_text="是否已结算")
    settlement_statement = models.ForeignKey(
        "SettlementStatement", on_delete=models.SET_NULL,
        related_name="orders", null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    refunded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "channel_orders"
        ordering = ["-id"]

    def save(self, *args, **kwargs):
        if not self.ticket_amount and self.quantity and self.unit_price:
            self.ticket_amount = self.unit_price * self.quantity
        super().save(*args, **kwargs)


class SettlementStatement(models.Model):
    """渠道结算单。"""

    STATUS_CHOICES = [
        ("generated", "已生成"),
        ("confirmed", "已确认"),
        ("settled", "已结算"),
    ]

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="statements")
    statement_no = models.CharField(max_length=64, unique=True)
    period_start = models.DateField()
    period_end = models.DateField()
    total_tickets = models.IntegerField(default=0)
    total_ticket_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_commission = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    refund_tickets = models.IntegerField(default=0)
    refund_ticket_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    refund_commission = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_settlement_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="generated")
    remark = models.TextField(blank=True, default="")
    generated_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "settlement_statements"
        ordering = ["-id"]

    @transaction.atomic
    def calculate_summary(self):
        """计算结算单汇总数据。"""
        orders = ChannelOrder.objects.filter(
            channel=self.channel,
            created_at__date__gte=self.period_start,
            created_at__date__lte=self.period_end,
        )

        paid_orders = orders.filter(status="paid")
        partially_refunded_orders = orders.filter(status="partially_refunded")
        refunded_orders = orders.filter(status="refunded")

        self.total_tickets = sum(o.quantity for o in paid_orders)
        self.total_ticket_amount = sum(o.ticket_amount for o in paid_orders)
        self.total_commission = sum(o.commission_amount for o in paid_orders)

        for o in partially_refunded_orders:
            effective_qty = o.quantity - o.refunded_quantity
            if effective_qty > 0:
                effective_ratio = Decimal(effective_qty) / Decimal(o.quantity)
                self.total_tickets += effective_qty
                self.total_ticket_amount += o.ticket_amount * effective_ratio
                self.total_commission += o.commission_amount * effective_ratio

            refund_ratio = Decimal(o.refunded_quantity) / Decimal(o.quantity)
            self.refund_tickets += o.refunded_quantity
            self.refund_ticket_amount += o.ticket_amount * refund_ratio
            self.refund_commission += o.commission_amount * refund_ratio

        self.refund_tickets += sum(o.refunded_quantity for o in refunded_orders)
        self.refund_ticket_amount += sum(o.ticket_amount for o in refunded_orders)
        self.refund_commission += sum(o.commission_amount for o in refunded_orders)

        self.net_settlement_amount = (
            self.total_ticket_amount - self.total_commission
            - self.refund_ticket_amount + self.refund_commission
        )

        self.save(
            update_fields=[
                "total_tickets", "total_ticket_amount", "total_commission",
                "refund_tickets", "refund_ticket_amount", "refund_commission",
                "net_settlement_amount",
            ]
        )


class SettlementItem(models.Model):
    """结算明细。"""

    ITEM_TYPE_CHOICES = [
        ("sale", "销售"),
        ("refund", "退票"),
    ]

    statement = models.ForeignKey(SettlementStatement, on_delete=models.CASCADE, related_name="items")
    order = models.ForeignKey(ChannelOrder, on_delete=models.CASCADE, related_name="settlement_items")
    item_type = models.CharField(max_length=16, choices=ITEM_TYPE_CHOICES, default="sale")
    quantity = models.IntegerField(default=0)
    ticket_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "settlement_items"
        ordering = ["-id"]
