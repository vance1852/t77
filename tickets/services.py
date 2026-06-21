import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from .models import (
    Channel, ChannelOrder, CommissionRule, Performance, PerformanceQuota,
    QuotaHold, SettlementItem, SettlementStatement,
)


class QuotaService:
    """配额服务。"""

    @staticmethod
    @transaction.atomic
    def allocate_quota(performance_id, channel_id, allocated_quantity):
        """
        分配场次配额给渠道。
        校验总配额不能超过场次总座位数。
        """
        perf = Performance.objects.select_for_update().get(pk=performance_id)
        channel = Channel.objects.get(pk=channel_id) if channel_id else None

        existing_quotas = PerformanceQuota.objects.filter(performance=perf)
        if channel:
            existing_quotas = existing_quotas.exclude(channel=channel)
        else:
            existing_quotas = existing_quotas.exclude(channel__isnull=True)

        total_allocated = sum(q.allocated for q in existing_quotas)

        if total_allocated + allocated_quantity > perf.total_seats:
            raise ValueError(
                f"配额分配超出总座位数：已分配{total_allocated}，新增{allocated_quantity}，总座位{perf.total_seats}"
            )

        quota, created = PerformanceQuota.objects.get_or_create(
            performance=perf,
            channel=channel,
            defaults={"allocated": allocated_quantity, "sold": 0, "held": 0}
        )
        if not created:
            if allocated_quantity < quota.sold + quota.held:
                raise ValueError(
                    f"配额不能低于已售+占用：已售{quota.sold}，占用{quota.held}，拟分配{allocated_quantity}"
                )
            quota.allocated = allocated_quantity
            quota.save(update_fields=["allocated", "updated_at"])

        return quota

    @staticmethod
    @transaction.atomic
    def adjust_quota(quota_id, delta):
        """
        动态调整配额（增加或减少）。
        delta > 0 增加，delta < 0 减少。
        减少时不能少于已售+占用；增加时不能超过场次总座位数。
        """
        quota = PerformanceQuota.objects.select_for_update().select_related("performance").get(pk=quota_id)
        new_allocated = quota.allocated + delta

        if new_allocated < quota.sold + quota.held:
            raise ValueError(
                f"配额不能低于已售+占用：已售{quota.sold}，占用{quota.held}，拟分配{new_allocated}"
            )

        if new_allocated < 0:
            raise ValueError("配额不能为负")

        if delta > 0:
            other_quotas = PerformanceQuota.objects.filter(
                performance=quota.performance
            ).exclude(pk=quota.pk)
            other_total = sum(q.allocated for q in other_quotas)
            if other_total + new_allocated > quota.performance.total_seats:
                raise ValueError(
                    f"调整后总配额超出总座位数：其他配额{other_total}，本配额调至{new_allocated}，总座位{quota.performance.total_seats}"
                )

        quota.allocated = new_allocated
        quota.save(update_fields=["allocated", "updated_at"])
        return quota

    @staticmethod
    @transaction.atomic
    def reclaim_unused_quota(quota_id):
        """
        回收未使用配额（未售+未占用的部分）。
        将可用配额回收，allocated = sold + held。
        """
        quota = PerformanceQuota.objects.select_for_update().get(pk=quota_id)
        used = quota.sold + quota.held
        quota.allocated = used
        quota.save(update_fields=["allocated", "updated_at"])
        return quota

    @staticmethod
    @transaction.atomic
    def hold_quota(channel_id, performance_id, quantity, hold_minutes=15):
        """
        软占用配额。
        返回 QuotaHold 对象和 hold_token。
        """
        now = timezone.now()

        expired_holds = QuotaHold.objects.filter(
            status="active",
            expires_at__lt=now,
        )
        for hold in expired_holds:
            QuotaService._release_hold_internal(hold)

        try:
            quota = PerformanceQuota.objects.select_for_update().get(
                performance_id=performance_id,
                channel_id=channel_id,
            )
        except PerformanceQuota.DoesNotExist:
            raise ValueError(f"该渠道在此场次未分配配额：channel_id={channel_id}, performance_id={performance_id}")

        if quota.available < quantity:
            raise ValueError(
                f"配额不足：可用{quota.available}，需要{quantity}"
            )

        quota.held += quantity
        quota.save(update_fields=["held", "updated_at"])

        hold = QuotaHold.objects.create(
            quota=quota,
            channel_id=channel_id,
            performance_id=performance_id,
            quantity=quantity,
            hold_token=uuid.uuid4(),
            status="active",
            expires_at=now + timedelta(minutes=hold_minutes),
        )

        return hold

    @staticmethod
    @transaction.atomic
    def release_quota_hold(hold_token):
        """主动释放配额占用。"""
        hold = QuotaHold.objects.select_for_update().get(hold_token=hold_token)
        if hold.status != "active":
            return hold
        QuotaService._release_hold_internal(hold)
        return hold

    @staticmethod
    def _release_hold_internal(hold):
        """内部释放占用，需在事务内调用。"""
        quota = PerformanceQuota.objects.select_for_update().get(pk=hold.quota_id)
        quota.held = max(0, quota.held - hold.quantity)
        quota.save(update_fields=["held", "updated_at"])
        hold.status = "released"
        hold.save(update_fields=["status"])

    @staticmethod
    @transaction.atomic
    def consume_hold(hold_token):
        """
        消费配额占用（下单时调用）。
        将占用转为已售。
        """
        hold = QuotaHold.objects.select_for_update().get(hold_token=hold_token)
        if hold.status != "active":
            raise ValueError(f"配额占用状态无效：{hold.status}")

        if hold.is_expired:
            QuotaService._release_hold_internal(hold)
            raise ValueError("配额占用已过期")

        quota = PerformanceQuota.objects.select_for_update().get(pk=hold.quota_id)
        quota.held -= hold.quantity
        quota.sold += hold.quantity
        quota.save(update_fields=["held", "sold", "updated_at"])

        hold.status = "consumed"
        hold.save(update_fields=["status"])

        return hold

    @staticmethod
    def get_quota_status(performance_id, channel_id=None):
        """获取某场次某渠道的配额状态。"""
        if channel_id:
            quotas = PerformanceQuota.objects.filter(
                performance_id=performance_id, channel_id=channel_id
            )
        else:
            quotas = PerformanceQuota.objects.filter(performance_id=performance_id)
        return quotas


class ChannelOrderService:
    """渠道订单服务。"""

    @staticmethod
    @transaction.atomic
    def create_channel_order(
        channel_id, performance_id, quantity, hold_token=None,
        channel_order_no="", customer_name="", customer_phone=""
    ):
        """
        创建渠道订单。
        流程：校验配额 -> 扣减配额 -> 扣减实际库存 -> 计算佣金 -> 创建订单
        """
        channel = Channel.objects.get(pk=channel_id)
        perf = Performance.objects.select_for_update().get(pk=performance_id)

        if perf.remaining_seats < quantity:
            raise ValueError(f"库存不足：剩余{perf.remaining_seats}张，需要{quantity}张")

        try:
            quota = PerformanceQuota.objects.select_for_update().get(
                performance_id=performance_id,
                channel_id=channel_id,
            )
        except PerformanceQuota.DoesNotExist:
            raise ValueError(f"该渠道在此场次未分配配额：channel_id={channel_id}, performance_id={performance_id}")

        if hold_token:
            hold = QuotaHold.objects.select_for_update().get(hold_token=hold_token)
            if hold.status != "active":
                raise ValueError("配额占用无效")
            if hold.is_expired:
                QuotaService._release_hold_internal(hold)
                raise ValueError("配额占用已过期")
            if hold.quantity != quantity:
                raise ValueError(f"占用数量不匹配：占用{hold.quantity}张，下单{quantity}张")

            quota.held -= quantity
            quota.sold += quantity
            quota.save(update_fields=["held", "sold", "updated_at"])
            hold.status = "consumed"
            hold.save(update_fields=["status"])
        else:
            if quota.available < quantity:
                raise ValueError(
                    f"渠道配额不足：可用{quota.available}张，需要{quantity}张"
                )
            quota.sold += quantity
            quota.save(update_fields=["sold", "updated_at"])

        perf.sold_seats += quantity
        perf.save(update_fields=["sold_seats"])

        active_rule = CommissionRule.objects.filter(
            channel=channel, is_active=True
        ).order_by("-id").first()

        commission_amount = Decimal("0")
        if active_rule:
            commission_amount = active_rule.calculate_commission(quantity, perf.price)

        ticket_amount = perf.price * Decimal(quantity)

        order = ChannelOrder.objects.create(
            channel=channel,
            performance=perf,
            channel_order_no=channel_order_no,
            customer_name=customer_name,
            customer_phone=customer_phone,
            quantity=quantity,
            unit_price=perf.price,
            ticket_amount=ticket_amount,
            commission_amount=commission_amount,
            status="paid",
            hold_token=hold_token,
            is_settled=False,
        )

        return order

    @staticmethod
    @transaction.atomic
    def refund_channel_order(order_id, refund_quantity=None):
        """
        渠道退票。
        支持部分退票：退票后如果还有剩余票，状态为 partially_refunded；
        全部退完后状态为 refunded。
        refunded_quantity 跟踪累计退票数。
        退票时冲回对应的库存和配额，佣金按比例冲回。
        """
        order = ChannelOrder.objects.select_for_update().get(pk=order_id)

        if order.status == "refunded":
            raise ValueError("订单已全额退票，无法继续退票")
        if order.status not in ("paid", "partially_refunded"):
            raise ValueError(f"订单状态不允许退票：{order.status}")

        remaining_qty = order.quantity - order.refunded_quantity
        if remaining_qty <= 0:
            raise ValueError("订单无可退票数量")

        if refund_quantity is None:
            refund_qty = remaining_qty
        else:
            refund_qty = refund_quantity

        if refund_qty <= 0:
            raise ValueError("退票数量必须大于0")
        if refund_qty > remaining_qty:
            raise ValueError(f"退票数量超过剩余可退数量：剩余{remaining_qty}张，请求退{refund_qty}张")

        perf = Performance.objects.select_for_update().get(pk=order.performance_id)
        perf.sold_seats = max(0, perf.sold_seats - refund_qty)
        perf.save(update_fields=["sold_seats"])

        quota = PerformanceQuota.objects.select_for_update().get(
            performance_id=order.performance_id,
            channel_id=order.channel_id,
        )
        quota.sold = max(0, quota.sold - refund_qty)
        quota.save(update_fields=["sold", "updated_at"])

        refund_ratio = Decimal(refund_qty) / Decimal(order.quantity)
        refund_ticket_amount = order.ticket_amount * refund_ratio
        refund_commission_amount = order.commission_amount * refund_ratio

        order.refunded_quantity += refund_qty

        if order.refunded_quantity >= order.quantity:
            order.status = "refunded"
        else:
            order.status = "partially_refunded"

        order.refunded_at = timezone.now()
        order.save(update_fields=["status", "refunded_quantity", "refunded_at"])

        return order, {
            "refund_quantity": refund_qty,
            "refund_ticket_amount": refund_ticket_amount,
            "refund_commission_amount": refund_commission_amount,
            "remaining_quantity": order.quantity - order.refunded_quantity,
        }


class SettlementService:
    """结算服务。"""

    @staticmethod
    @transaction.atomic
    def generate_statement(channel_id, period_start, period_end, statement_no=None):
        """
        生成渠道结算单。
        """
        channel = Channel.objects.get(pk=channel_id)

        if not statement_no:
            statement_no = f"ST{channel_id}{period_start.strftime('%Y%m%d')}{period_end.strftime('%Y%m%d')}"

        statement = SettlementStatement.objects.create(
            channel=channel,
            statement_no=statement_no,
            period_start=period_start,
            period_end=period_end,
            status="generated",
        )

        statement.calculate_summary()

        paid_orders = ChannelOrder.objects.filter(
            channel=channel,
            status="paid",
            created_at__date__gte=period_start,
            created_at__date__lte=period_end,
        )
        partially_refunded_orders = ChannelOrder.objects.filter(
            channel=channel,
            status="partially_refunded",
            created_at__date__gte=period_start,
            created_at__date__lte=period_end,
        )
        refunded_orders = ChannelOrder.objects.filter(
            channel=channel,
            status="refunded",
            refunded_at__date__gte=period_start,
            refunded_at__date__lte=period_end,
        )

        items = []
        for order in paid_orders:
            items.append(SettlementItem(
                statement=statement,
                order=order,
                item_type="sale",
                quantity=order.quantity,
                ticket_amount=order.ticket_amount,
                commission_amount=order.commission_amount,
            ))
            order.is_settled = True
            order.settlement_statement = statement
            order.save(update_fields=["is_settled", "settlement_statement"])

        for order in partially_refunded_orders:
            effective_qty = order.quantity - order.refunded_quantity
            if effective_qty > 0:
                effective_ratio = Decimal(effective_qty) / Decimal(order.quantity)
                items.append(SettlementItem(
                    statement=statement,
                    order=order,
                    item_type="sale",
                    quantity=effective_qty,
                    ticket_amount=order.ticket_amount * effective_ratio,
                    commission_amount=order.commission_amount * effective_ratio,
                ))
            refund_ratio = Decimal(order.refunded_quantity) / Decimal(order.quantity)
            items.append(SettlementItem(
                statement=statement,
                order=order,
                item_type="refund",
                quantity=order.refunded_quantity,
                ticket_amount=-(order.ticket_amount * refund_ratio),
                commission_amount=-(order.commission_amount * refund_ratio),
            ))
            order.is_settled = True
            order.settlement_statement = statement
            order.save(update_fields=["is_settled", "settlement_statement"])

        for order in refunded_orders:
            items.append(SettlementItem(
                statement=statement,
                order=order,
                item_type="refund",
                quantity=order.quantity,
                ticket_amount=-order.ticket_amount,
                commission_amount=-order.commission_amount,
            ))

        SettlementItem.objects.bulk_create(items)

        return statement

    @staticmethod
    @transaction.atomic
    def confirm_statement(statement_id):
        """确认结算单。"""
        statement = SettlementStatement.objects.select_for_update().get(pk=statement_id)
        if statement.status != "generated":
            raise ValueError(f"结算单状态不允许确认：{statement.status}")
        statement.status = "confirmed"
        statement.confirmed_at = timezone.now()
        statement.save(update_fields=["status", "confirmed_at"])
        return statement

    @staticmethod
    @transaction.atomic
    def settle_statement(statement_id):
        """标记结算单已结算。"""
        statement = SettlementStatement.objects.select_for_update().get(pk=statement_id)
        if statement.status != "confirmed":
            raise ValueError(f"结算单状态不允许结算：{statement.status}")
        statement.status = "settled"
        statement.settled_at = timezone.now()
        statement.save(update_fields=["status", "settled_at"])
        return statement


class StatsService:
    """统计服务。"""

    @staticmethod
    def get_quota_monitoring(performance_id=None):
        """
        配额使用监控。
        返回各渠道配额/已售/剩余/占用情况。
        """
        queryset = PerformanceQuota.objects.select_related("channel", "performance")
        if performance_id:
            queryset = queryset.filter(performance_id=performance_id)

        result = []
        for q in queryset:
            result.append({
                "performance_id": q.performance_id,
                "performance_title": q.performance.show.title if q.performance.show else "",
                "channel_id": q.channel_id,
                "channel_name": q.channel_name,
                "allocated": q.allocated,
                "sold": q.sold,
                "held": q.held,
                "available": q.available,
                "sell_rate": round(q.sold / q.allocated * 100, 2) if q.allocated > 0 else 0,
            })
        return result

    @staticmethod
    def get_channel_performance_ranking(start_date=None, end_date=None, limit=10):
        """
        渠道业绩排行。
        按售票数/票款/佣金排序。
        """
        orders_qs = ChannelOrder.objects.filter(status="paid")
        if start_date:
            orders_qs = orders_qs.filter(created_at__date__gte=start_date)
        if end_date:
            orders_qs = orders_qs.filter(created_at__date__lte=end_date)

        from django.db.models import Count, Sum
        stats = orders_qs.values("channel_id", "channel__name").annotate(
            total_orders=Count("id"),
            total_tickets=Sum("quantity"),
            total_ticket_amount=Sum("ticket_amount"),
            total_commission=Sum("commission_amount"),
        ).order_by("-total_tickets")[:limit]

        return list(stats)

    @staticmethod
    def get_commission_cost_stats(start_date=None, end_date=None):
        """
        佣金成本统计。
        """
        orders_qs = ChannelOrder.objects.filter(status="paid")
        if start_date:
            orders_qs = orders_qs.filter(created_at__date__gte=start_date)
        if end_date:
            orders_qs = orders_qs.filter(created_at__date__lte=end_date)

        from django.db.models import Sum
        stats = orders_qs.values("channel_id", "channel__name").annotate(
            total_ticket_amount=Sum("ticket_amount"),
            total_commission=Sum("commission_amount"),
        )

        result = []
        total_ticket = Decimal("0")
        total_commission = Decimal("0")
        for s in stats:
            ta = s["total_ticket_amount"] or Decimal("0")
            tc = s["total_commission"] or Decimal("0")
            total_ticket += ta
            total_commission += tc
            rate = (tc / ta * 100) if ta > 0 else Decimal("0")
            result.append({
                "channel_id": s["channel_id"],
                "channel_name": s["channel__name"],
                "total_ticket_amount": ta,
                "total_commission": tc,
                "commission_rate": round(rate, 2),
            })

        overall_rate = (total_commission / total_ticket * 100) if total_ticket > 0 else Decimal("0")
        return {
            "channels": result,
            "total_ticket_amount": total_ticket,
            "total_commission": total_commission,
            "overall_commission_rate": round(overall_rate, 2),
        }
