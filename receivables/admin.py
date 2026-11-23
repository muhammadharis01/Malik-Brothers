from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import (
    Consignment,
    PaymentReceipt,
    LossDamageSettlement,
    InboundTruckChallan,
    ChangeLog,
)


@admin.register(InboundTruckChallan)
class InboundTruckChallanAdmin(ModelAdmin):
    list_display = (
        'truck_challan_key',
        'truck_no',
        'challan_no',
        'no_of_builties',
        'builties_entered',
        'total_nags_count',
        'status',
        'created_at',
    )
    search_fields = ('truck_challan_key', 'truck_no', 'challan_no')
    list_filter = ('status', 'created_at')
    readonly_fields = ('truck_challan_key', 'created_at', 'updated_at', 'created_by')

    @admin.display(description='Builties Entered')
    def builties_entered(self, obj):
        return f"{obj.builties_count} / {obj.no_of_builties}"

    @admin.display(description='Total Nags')
    def total_nags_count(self, obj):
        return obj.total_nags


@admin.register(Consignment)
class ConsignmentAdmin(ModelAdmin):
    list_display = (
        'form_no',
        'builty_no',
        'truck_challan',
        'nags',
        'customer_name',
        'total_amount',
        'advance_received',
        'receivable_amount',
        'goods_condition',
        'delivery_status',
        'status',
    )
    search_fields = ('form_no', 'builty_no', 'customer_name', 'contact_number', 'truck_challan__truck_challan_key')
    list_filter = ('status', 'delivery_status', 'goods_condition', 'customer_type', 'delivery_mode')
    readonly_fields = ('form_no', 'receivable_amount', 'created_at', 'updated_at', 'created_by')


@admin.register(PaymentReceipt)
class PaymentReceiptAdmin(ModelAdmin):
    list_display = (
        'receipt_id',
        'consignment',
        'receipt_date',
        'amount_received',
        'received_via',
        'agent',
        'payment_mode',
        'receivable_after',
    )
    search_fields = ('consignment__form_no', 'consignment__builty_no', 'agent__agent_name')
    list_filter = ('received_via', 'payment_mode', 'receipt_date')
    readonly_fields = ('created_at', 'created_by', 'receivable_after')


@admin.register(LossDamageSettlement)
class LossDamageSettlementAdmin(ModelAdmin):
    list_display = (
        'settlement_id',
        'consignment',
        'goods_condition',
        'amount_paid_to_customer',
        'settlement_date',
    )
    search_fields = ('consignment__form_no', 'consignment__builty_no')
    readonly_fields = ('created_at', 'created_by')


@admin.register(ChangeLog)
class ChangeLogAdmin(ModelAdmin):
    list_display = (
        'log_id',
        'timestamp',
        'action_type',
        'truck_challan_key',
        'builty_no',
        'field_name',
        'old_value',
        'new_value',
        'user',
    )
    search_fields = ('truck_challan_key', 'builty_no', 'action_type', 'field_name', 'user__username')
    list_filter = ('action_type', 'timestamp')
    readonly_fields = (
        'log_id',
        'truck_challan_key',
        'builty_no',
        'action_type',
        'field_name',
        'old_value',
        'new_value',
        'user',
        'timestamp',
        'ip_address',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
