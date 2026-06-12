from rest_framework import serializers

from .models import Performance, Show, TicketOrder


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
