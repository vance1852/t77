"""初始化内置管理员与种子业务数据（幂等）。"""
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from tickets.models import Performance, Show, TicketOrder


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

        shows = [
            Show.objects.create(title="星河巡回演唱会", troupe="星河乐团", genre="concert", status="on_sale"),
            Show.objects.create(title="金陵往事话剧", troupe="城南剧社", genre="drama", status="on_sale"),
            Show.objects.create(title="敦煌音乐剧", troupe="丝路艺术团", genre="musical", status="upcoming"),
            Show.objects.create(title="经典戏曲专场", troupe="梨园名家", genre="opera", status="ended"),
        ]

        now = datetime.now().replace(microsecond=0)
        perfs = [
            Performance.objects.create(show=shows[0], hall="一号厅", start_at=now + timedelta(days=3), total_seats=1200, sold_seats=860, price=380),
            Performance.objects.create(show=shows[0], hall="一号厅", start_at=now + timedelta(days=4), total_seats=1200, sold_seats=300, price=380),
            Performance.objects.create(show=shows[1], hall="小剧场", start_at=now + timedelta(days=2), total_seats=300, sold_seats=290, price=180),
            Performance.objects.create(show=shows[2], hall="大剧院", start_at=now + timedelta(days=20), total_seats=900, sold_seats=0, price=280),
        ]

        TicketOrder.objects.create(performance=perfs[0], customer_name="陈静", phone="13900001111", quantity=2, amount=760, status="paid")
        TicketOrder.objects.create(performance=perfs[2], customer_name="刘洋", phone="13900002222", quantity=4, amount=720, status="paid")
        TicketOrder.objects.create(performance=perfs[0], customer_name="孙琳", phone="13900003333", quantity=1, amount=380, status="cancelled")

        self.stdout.write("种子数据初始化完成")
