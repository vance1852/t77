"""初始化内置管理员与种子业务数据（幂等）。"""
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from tickets.models import (
    Channel, ChannelOrder, CommissionRule, CommissionTier, Performance,
    PerformanceQuota, Show, TicketOrder,
)
from tickets.services import ChannelOrderService, QuotaService


class Command(BaseCommand):
    help = "初始化管理员与演出票务种子数据"

    def handle(self, *args, **options):
        username = settings.DEFAULT_ADMIN_USERNAME
        password = settings.DEFAULT_ADMIN_PASSWORD
        if not User.objects.filter(username=username).exists():
            User.objects.create_superuser(username=username, password=password, first_name="平台管理员")
            self.stdout.write("已创建管理员账号")

        if Show.objects.exists():
            self.stdout.write("业务数据已存在，跳过")
            return

        with transaction.atomic():
            self._seed_shows_and_performances()
            self._seed_channels()
            self._seed_commission_rules()
            self._seed_quotas()
            self._seed_direct_orders()
            self._seed_channel_orders()

        self.stdout.write("种子数据初始化完成")

    def _seed_shows_and_performances(self):
        shows = [
            Show.objects.create(title="星河巡回演唱会", troupe="星河乐团", genre="concert", status="on_sale"),
            Show.objects.create(title="金陵往事话剧", troupe="城南剧社", genre="drama", status="on_sale"),
            Show.objects.create(title="敦煌音乐剧", troupe="丝路艺术团", genre="musical", status="upcoming"),
            Show.objects.create(title="经典戏曲专场", troupe="梨园名家", genre="opera", status="ended"),
        ]

        now = timezone.now().replace(microsecond=0)
        perfs = [
            Performance.objects.create(show=shows[0], hall="一号厅", start_at=now + timedelta(days=3), total_seats=1200, sold_seats=0, price=380),
            Performance.objects.create(show=shows[0], hall="一号厅", start_at=now + timedelta(days=4), total_seats=1200, sold_seats=0, price=380),
            Performance.objects.create(show=shows[1], hall="小剧场", start_at=now + timedelta(days=2), total_seats=300, sold_seats=0, price=180),
            Performance.objects.create(show=shows[2], hall="大剧院", start_at=now + timedelta(days=20), total_seats=900, sold_seats=0, price=280),
        ]

        self.shows = shows
        self.perfs = perfs
        self.stdout.write("已创建演出与场次数据")

    def _seed_direct_orders(self):
        order1 = TicketOrder.objects.create(
            performance=self.perfs[0], customer_name="陈静", phone="13900001111",
            quantity=2, amount=760, status="paid"
        )
        order2 = TicketOrder.objects.create(
            performance=self.perfs[2], customer_name="刘洋", phone="13900002222",
            quantity=4, amount=720, status="paid"
        )
        TicketOrder.objects.create(
            performance=self.perfs[0], customer_name="孙琳", phone="13900003333",
            quantity=1, amount=380, status="cancelled"
        )

        direct_quota_1 = PerformanceQuota.objects.get(performance=self.perfs[0], channel__isnull=True)
        direct_quota_1.sold += 2
        direct_quota_1.save(update_fields=["sold", "updated_at"])
        self.perfs[0].sold_seats += 2
        self.perfs[0].save(update_fields=["sold_seats"])

        direct_quota_3 = PerformanceQuota.objects.get(performance=self.perfs[2], channel__isnull=True)
        direct_quota_3.sold += 4
        direct_quota_3.save(update_fields=["sold", "updated_at"])
        self.perfs[2].sold_seats += 4
        self.perfs[2].save(update_fields=["sold_seats"])

        self.stdout.write("已创建直销订单数据")

    def _seed_channels(self):
        self.channels = [
            Channel.objects.create(
                name="大麦网",
                code="damai",
                channel_type="platform",
                contact_person="张经理",
                contact_phone="13800001111",
                contact_email="zhang@damai.com",
                settlement_method="bank_transfer",
                settlement_cycle="weekly",
                settlement_account="招商银行 6226 **** 8888",
                status="active",
                remark="国内主流票务平台",
            ),
            Channel.objects.create(
                name="摩天轮票务",
                code="motianlun",
                channel_type="platform",
                contact_person="李总监",
                contact_phone="13800002222",
                contact_email="li@mtl.com",
                settlement_method="alipay",
                settlement_cycle="monthly",
                settlement_account="finance@mtl.com",
                status="active",
                remark="二级票务平台",
            ),
            Channel.objects.create(
                name="北京总代理",
                code="bj_agent",
                channel_type="agent",
                contact_person="王总",
                contact_phone="13900003333",
                contact_email="wang@bjagent.com",
                settlement_method="bank_transfer",
                settlement_cycle="monthly",
                settlement_account="工商银行 6222 **** 6666",
                status="active",
                remark="北京地区一级代理",
            ),
            Channel.objects.create(
                name="企业团购网",
                code="group_buy",
                channel_type="group",
                contact_person="赵经理",
                contact_phone="13700004444",
                contact_email="zhao@groupbuy.com",
                settlement_method="wechat",
                settlement_cycle="daily",
                settlement_account="企业微信商户号 1234567890",
                status="active",
                remark="企业团购渠道",
            ),
        ]
        self.stdout.write("已创建渠道数据")

    def _seed_commission_rules(self):
        CommissionRule.objects.create(
            channel=self.channels[0],
            name="大麦网标准佣金",
            rule_type="percentage",
            percentage_rate=10,
            fixed_amount=0,
            is_active=True,
        )

        fixed_rule = CommissionRule.objects.create(
            channel=self.channels[2],
            name="北京代理固定佣金",
            rule_type="fixed",
            percentage_rate=0,
            fixed_amount=30,
            is_active=True,
        )

        tiered_rule = CommissionRule.objects.create(
            channel=self.channels[1],
            name="摩天轮阶梯佣金",
            rule_type="tiered",
            tier_base="quantity",
            is_active=True,
        )
        CommissionTier.objects.create(
            rule=tiered_rule, min_value=0, max_value=99, tier_type="percentage", rate=8
        )
        CommissionTier.objects.create(
            rule=tiered_rule, min_value=100, max_value=499, tier_type="percentage", rate=12
        )
        CommissionTier.objects.create(
            rule=tiered_rule, min_value=500, max_value=None, tier_type="percentage", rate=15
        )

        group_rule = CommissionRule.objects.create(
            channel=self.channels[3],
            name="团购阶梯佣金",
            rule_type="tiered",
            tier_base="amount",
            is_active=True,
        )
        CommissionTier.objects.create(
            rule=group_rule, min_value=0, max_value=9999, tier_type="fixed", rate=20
        )
        CommissionTier.objects.create(
            rule=group_rule, min_value=10000, max_value=49999, tier_type="fixed", rate=35
        )
        CommissionTier.objects.create(
            rule=group_rule, min_value=50000, max_value=None, tier_type="percentage", rate=12
        )

        self.stdout.write("已创建佣金规则数据")

    def _seed_quotas(self):
        QuotaService.allocate_quota(
            performance_id=self.perfs[0].pk,
            channel_id=None,
            allocated_quantity=400,
        )
        QuotaService.allocate_quota(
            performance_id=self.perfs[0].pk,
            channel_id=self.channels[0].pk,
            allocated_quantity=500,
        )
        QuotaService.allocate_quota(
            performance_id=self.perfs[0].pk,
            channel_id=self.channels[1].pk,
            allocated_quantity=200,
        )
        QuotaService.allocate_quota(
            performance_id=self.perfs[0].pk,
            channel_id=self.channels[2].pk,
            allocated_quantity=100,
        )

        QuotaService.allocate_quota(
            performance_id=self.perfs[1].pk,
            channel_id=None,
            allocated_quantity=600,
        )
        QuotaService.allocate_quota(
            performance_id=self.perfs[1].pk,
            channel_id=self.channels[0].pk,
            allocated_quantity=400,
        )
        QuotaService.allocate_quota(
            performance_id=self.perfs[1].pk,
            channel_id=self.channels[3].pk,
            allocated_quantity=200,
        )

        QuotaService.allocate_quota(
            performance_id=self.perfs[2].pk,
            channel_id=None,
            allocated_quantity=100,
        )
        QuotaService.allocate_quota(
            performance_id=self.perfs[2].pk,
            channel_id=self.channels[0].pk,
            allocated_quantity=150,
        )
        QuotaService.allocate_quota(
            performance_id=self.perfs[2].pk,
            channel_id=self.channels[2].pk,
            allocated_quantity=50,
        )

        self.stdout.write("已创建配额数据")

    def _seed_channel_orders(self):
        order1 = ChannelOrderService.create_channel_order(
            channel_id=self.channels[0].pk,
            performance_id=self.perfs[0].pk,
            quantity=5,
            channel_order_no="DM20240601001",
            customer_name="周杰",
            customer_phone="13600005555",
        )

        order2 = ChannelOrderService.create_channel_order(
            channel_id=self.channels[1].pk,
            performance_id=self.perfs[0].pk,
            quantity=3,
            channel_order_no="MTL20240601001",
            customer_name="吴芳",
            customer_phone="13600006666",
        )

        order3 = ChannelOrderService.create_channel_order(
            channel_id=self.channels[2].pk,
            performance_id=self.perfs[0].pk,
            quantity=10,
            channel_order_no="BJA20240601001",
            customer_name="郑伟",
            customer_phone="13600007777",
        )

        order4 = ChannelOrderService.create_channel_order(
            channel_id=self.channels[0].pk,
            performance_id=self.perfs[1].pk,
            quantity=8,
            channel_order_no="DM20240602001",
            customer_name="孙丽",
            customer_phone="13600008888",
        )

        order5 = ChannelOrderService.create_channel_order(
            channel_id=self.channels[3].pk,
            performance_id=self.perfs[1].pk,
            quantity=20,
            channel_order_no="GB20240602001",
            customer_name="某科技公司",
            customer_phone="010-88888888",
        )

        order6 = ChannelOrderService.create_channel_order(
            channel_id=self.channels[0].pk,
            performance_id=self.perfs[2].pk,
            quantity=2,
            channel_order_no="DM20240603001",
            customer_name="钱明",
            customer_phone="13600009999",
        )

        refund_order = ChannelOrderService.create_channel_order(
            channel_id=self.channels[1].pk,
            performance_id=self.perfs[0].pk,
            quantity=4,
            channel_order_no="MTL20240601002",
            customer_name="冯雪",
            customer_phone="13700001111",
        )
        ChannelOrderService.refund_channel_order(order_id=refund_order.pk)

        self.stdout.write("已创建渠道订单数据")
