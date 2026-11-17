from django.contrib import admin
from unfold.admin import ModelAdmin
from .models import CustomerMaster, AgentMaster


@admin.register(CustomerMaster)
class CustomerMasterAdmin(ModelAdmin):
    list_display = (
        'customer_id',
        'customer_name',
        'contact_number',
        'area_region',
        'status',
        'billing_cycle',
        'credit_limit',
        'hold_flag',
    )
    search_fields = ('customer_name', 'contact_number', 'area_region')
    list_filter = ('status', 'billing_cycle', 'hold_flag', 'area_region')
    readonly_fields = ('created_at', 'updated_at', 'created_by')
    fieldsets = (
        ('Basic Information', {
            'fields': ('customer_name', 'contact_number', 'alternate_contact', 'status')
        }),
        ('Address & Region', {
            'fields': ('address', 'delivery_address', 'area_region')
        }),
        ('Billing & Credit Controls', {
            'fields': ('billing_cycle', 'credit_limit', 'hold_flag', 'branch_id')
        }),
        ('Audit Information', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AgentMaster)
class AgentMasterAdmin(ModelAdmin):
    list_display = (
        'agent_id',
        'agent_name',
        'contact_number',
        'area_region',
        'status',
    )
    search_fields = ('agent_name', 'contact_number', 'area_region')
    list_filter = ('status', 'area_region')
    readonly_fields = ('created_at', 'updated_at', 'created_by')
    fieldsets = (
        ('Agent Information', {
            'fields': ('agent_name', 'contact_number', 'area_region', 'status', 'branch_id')
        }),
        ('Audit Information', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.pk and not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
