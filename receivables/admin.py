from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import Consignment, PaymentReceipt, LossDamageSettlement


@admin.register(Consignment)
class ConsignmentAdmin(ModelAdmin):
    list_display = (
        'form_no',
        'builty_no',
        'customer_name',
        'total_amount',
        'advance_received',
        'receivable_amount',
        'delivery_status',
        'goods_condition',
        'status',
    )
    search_fields = ('form_no', 'builty_no', 'customer_name', 'contact_number')
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
