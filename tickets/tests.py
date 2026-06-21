from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from .models import (
    Channel, ChannelOrder, CommissionRule, CommissionTier,
    Performance, PerformanceQuota, Show,
)
from .services import ChannelOrderService, QuotaService


class Bug1AdjustQuotaOverflowTest(TestCase):
    """Bug1: 配额调整后总配额不应超过演出总库存。"""

    def setUp(self):
        self.user = User.objects.create_superuser("testadmin", password="test123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.show = Show.objects.create(title="测试演出", status="on_sale")
        self.perf = Performance.objects.create(
            show=self.show, hall="测试厅",
            start_at=timezone.now() + timedelta(days=3),
            total_seats=100, price=Decimal("200"),
        )
        self.ch_a = Channel.objects.create(name="渠道A", code="ch_a")
        self.ch_b = Channel.objects.create(name="渠道B", code="ch_b")

        CommissionRule.objects.create(
            channel=self.ch_a, name="10%佣金",
            rule_type="percentage", percentage_rate=10, is_active=True,
        )
        CommissionRule.objects.create(
            channel=self.ch_b, name="15%佣金",
            rule_type="percentage", percentage_rate=15, is_active=True,
        )

        self.quota_a = QuotaService.allocate_quota(self.perf.pk, self.ch_a.pk, 60)
        self.quota_b = QuotaService.allocate_quota(self.perf.pk, self.ch_b.pk, 40)

    def test_adjust_quota_cannot_exceed_total_seats(self):
        """增加配额时，总配额不能超过总座位数。"""
        with self.assertRaises(ValueError) as ctx:
            QuotaService.adjust_quota(self.quota_a.pk, delta=50)
        self.assertIn("超出总座位数", str(ctx.exception))

    def test_adjust_quota_within_limit_succeeds(self):
        """增加配额在合理范围内应成功。"""
        quota = QuotaService.adjust_quota(self.quota_a.pk, delta=10)
        self.assertEqual(quota.allocated, 70)

    def test_adjust_quota_negative_succeeds(self):
        """减少配额应成功。"""
        quota = QuotaService.adjust_quota(self.quota_a.pk, delta=-10)
        self.assertEqual(quota.allocated, 50)


class Bug2PartialRefundTest(TestCase):
    """Bug2: 部分退票后订单应保持可继续退票状态。"""

    def setUp(self):
        self.user = User.objects.create_superuser("testadmin", password="test123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.show = Show.objects.create(title="测试演出", status="on_sale")
        self.perf = Performance.objects.create(
            show=self.show, hall="测试厅",
            start_at=timezone.now() + timedelta(days=3),
            total_seats=100, price=Decimal("200"),
        )
        self.channel = Channel.objects.create(name="测试渠道", code="test_ch")
        CommissionRule.objects.create(
            channel=self.channel, name="10%佣金",
            rule_type="percentage", percentage_rate=10, is_active=True,
        )

        QuotaService.allocate_quota(self.perf.pk, self.channel.pk, 80)
        QuotaService.allocate_quota(self.perf.pk, None, 20)

        self.order = ChannelOrderService.create_channel_order(
            channel_id=self.channel.pk,
            performance_id=self.perf.pk,
            quantity=10,
            customer_name="测试用户",
        )

    def test_partial_refund_sets_partially_refunded_status(self):
        """部分退票后状态应为 partially_refunded。"""
        order, refund_info = ChannelOrderService.refund_channel_order(
            order_id=self.order.pk, refund_quantity=3
        )
        self.assertEqual(order.status, "partially_refunded")
        self.assertEqual(order.refunded_quantity, 3)
        self.assertEqual(order.quantity, 10)
        self.assertEqual(refund_info["remaining_quantity"], 7)

    def test_partial_refund_then_full_refund(self):
        """部分退票后可以继续退完剩余票。"""
        ChannelOrderService.refund_channel_order(
            order_id=self.order.pk, refund_quantity=3
        )
        order2, refund_info2 = ChannelOrderService.refund_channel_order(
            order_id=self.order.pk, refund_quantity=7
        )
        self.assertEqual(order2.status, "refunded")
        self.assertEqual(order2.refunded_quantity, 10)
        self.assertEqual(refund_info2["remaining_quantity"], 0)

    def test_cannot_refund_more_than_remaining(self):
        """退票数量不能超过剩余可退数量。"""
        ChannelOrderService.refund_channel_order(
            order_id=self.order.pk, refund_quantity=8
        )
        with self.assertRaises(ValueError) as ctx:
            ChannelOrderService.refund_channel_order(
                order_id=self.order.pk, refund_quantity=5
            )
        self.assertIn("超过剩余可退数量", str(ctx.exception))

    def test_fully_refunded_order_cannot_refund_again(self):
        """全额退票后不能再退。"""
        ChannelOrderService.refund_channel_order(
            order_id=self.order.pk, refund_quantity=10
        )
        with self.assertRaises(ValueError) as ctx:
            ChannelOrderService.refund_channel_order(
                order_id=self.order.pk, refund_quantity=1
            )
        self.assertIn("已全额退票", str(ctx.exception))

    def test_partial_refund_restores_quota(self):
        """部分退票后配额应恢复。"""
        ChannelOrderService.refund_channel_order(
            order_id=self.order.pk, refund_quantity=3
        )
        quota = PerformanceQuota.objects.get(
            performance=self.perf, channel=self.channel
        )
        self.assertEqual(quota.sold, 7)

    def test_partial_refund_api(self):
        """API 部分退票测试。"""
        resp = self.client.post(
            f"/api/channel-orders/{self.order.pk}/refund",
            {"refund_quantity": 3},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(data["order"]["status"], "partially_refunded")
        self.assertEqual(data["order"]["refunded_quantity"], 3)
        self.assertEqual(data["refund_detail"]["remaining_quantity"], 7)


class Bug3NoQuotaHoldTest(TestCase):
    """Bug3: 没有配额的渠道创建占用应返回400而非500。"""

    def setUp(self):
        self.user = User.objects.create_superuser("testadmin", password="test123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.show = Show.objects.create(title="测试演出", status="on_sale")
        self.perf = Performance.objects.create(
            show=self.show, hall="测试厅",
            start_at=timezone.now() + timedelta(days=3),
            total_seats=100, price=Decimal("200"),
        )
        self.channel_with_quota = Channel.objects.create(name="有配额渠道", code="with_q")
        self.channel_without_quota = Channel.objects.create(name="无配额渠道", code="without_q")

        QuotaService.allocate_quota(self.perf.pk, self.channel_with_quota.pk, 50)
        QuotaService.allocate_quota(self.perf.pk, None, 50)

    def test_hold_quota_no_quota_returns_400(self):
        """无配额渠道创建占用应返回 400。"""
        resp = self.client.post(
            "/api/quota-holds",
            {
                "channel": self.channel_without_quota.pk,
                "performance": self.perf.pk,
                "quantity": 1,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("未分配配额", resp.json()["detail"])

    def test_create_order_no_quota_returns_400(self):
        """无配额渠道下单应返回 400。"""
        resp = self.client.post(
            "/api/channel-orders",
            {
                "channel": self.channel_without_quota.pk,
                "performance": self.perf.pk,
                "quantity": 1,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("未分配配额", resp.json()["detail"])

    def test_hold_quota_with_quota_succeeds(self):
        """有配额渠道创建占用应成功。"""
        resp = self.client.post(
            "/api/quota-holds",
            {
                "channel": self.channel_with_quota.pk,
                "performance": self.perf.pk,
                "quantity": 5,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class AdjustQuotaAPITest(TestCase):
    """配额调整 API 测试。"""

    def setUp(self):
        self.user = User.objects.create_superuser("testadmin", password="test123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        self.show = Show.objects.create(title="测试演出", status="on_sale")
        self.perf = Performance.objects.create(
            show=self.show, hall="测试厅",
            start_at=timezone.now() + timedelta(days=3),
            total_seats=100, price=Decimal("200"),
        )
        self.channel = Channel.objects.create(name="测试渠道", code="tq_ch")
        QuotaService.allocate_quota(self.perf.pk, self.channel.pk, 60)
        QuotaService.allocate_quota(self.perf.pk, None, 40)

    def test_adjust_quota_overflow_returns_400(self):
        """API: 调整配额超过总座位数应返回 400。"""
        quota = PerformanceQuota.objects.get(performance=self.perf, channel=self.channel)
        resp = self.client.post(
            f"/api/quotas/{quota.pk}/adjust",
            {"delta": 50},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("超出总座位数", resp.json()["detail"])

    def test_adjust_quota_valid_succeeds(self):
        """API: 合法调整配额应成功。"""
        quota = PerformanceQuota.objects.get(performance=self.perf, channel=self.channel)
        resp = self.client.post(
            f"/api/quotas/{quota.pk}/adjust",
            {"delta": 10},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["allocated"], 70)
