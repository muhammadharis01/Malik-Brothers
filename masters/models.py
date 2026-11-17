from decimal import Decimal
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class CustomerStatus(models.TextChoices):
    ACTIVE = 'Active', _('Active')
    INACTIVE = 'Inactive', _('Inactive')


class BillingCycle(models.TextChoices):
    DAILY = 'Daily', _('Daily')
    WEEKLY = 'Weekly', _('Weekly')
    MONTH_END = 'Month-end', _('Month-end')


class AgentStatus(models.TextChoices):
    ACTIVE = 'Active', _('Active')
    INACTIVE = 'Inactive', _('Inactive')


class CustomerMaster(models.Model):
    customer_id = models.AutoField(primary_key=True)
    customer_name = models.CharField(max_length=150, unique=True, verbose_name=_('Customer Name'))
    contact_number = models.CharField(max_length=30, verbose_name=_('Contact Number'))
    alternate_contact = models.CharField(max_length=30, blank=True, verbose_name=_('Alternate Contact'))
    address = models.CharField(max_length=300, blank=True, verbose_name=_('Address'))
    delivery_address = models.CharField(max_length=300, blank=True, verbose_name=_('Delivery Address'))
    area_region = models.CharField(max_length=80, blank=True, verbose_name=_('Area / Region'))
    status = models.CharField(
        max_length=10,
        choices=CustomerStatus.choices,
        default=CustomerStatus.ACTIVE,
        verbose_name=_('Status')
    )
    billing_cycle = models.CharField(
        max_length=15,
        choices=BillingCycle.choices,
        blank=True,
        verbose_name=_('Billing Cycle')
    )
    credit_limit = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_('Credit Limit')
    )
    hold_flag = models.BooleanField(default=False, verbose_name=_('Hold (Block Credit)'))
    branch_id = models.IntegerField(default=1, verbose_name=_('Branch ID'))
    
    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_customers',
        verbose_name=_('Created By')
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated At'))

    class Meta:
        db_table = 'customer_master'
        verbose_name = _('Customer Master')
        verbose_name_plural = _('Customer Masters')
        ordering = ['customer_name']
        indexes = [
            models.Index(fields=['customer_name']),
            models.Index(fields=['status']),
            models.Index(fields=['area_region']),
        ]

    def __str__(self):
        return f"{self.customer_name} ({self.area_region or 'No Area'})"

    def save(self, *args, **kwargs):
        if not self.delivery_address and self.address:
            self.delivery_address = self.address
        super().save(*args, **kwargs)

    def get_total_outstanding(self) -> Decimal:
        """
        Rule: A customer's total outstanding is not stored. It is calculated as
        the sum of receivable_amount of that customer's open consignments.
        """
        open_consignments = self.consignments.filter(status='Open')
        total = open_consignments.aggregate(models.Sum('receivable_amount'))['receivable_amount__sum']
        return total if total is not None else Decimal('0.00')


class AgentMaster(models.Model):
    agent_id = models.AutoField(primary_key=True)
    agent_name = models.CharField(max_length=100, verbose_name=_('Agent Name'))
    contact_number = models.CharField(max_length=30, verbose_name=_('Contact Number'))
    area_region = models.CharField(max_length=80, blank=True, verbose_name=_('Area / Region'))
    status = models.CharField(
        max_length=10,
        choices=AgentStatus.choices,
        default=AgentStatus.ACTIVE,
        verbose_name=_('Status')
    )
    branch_id = models.IntegerField(default=1, verbose_name=_('Branch ID'))
    
    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_agents',
        verbose_name=_('Created By')
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated At'))

    class Meta:
        db_table = 'agent_master'
        verbose_name = _('Agent Master')
        verbose_name_plural = _('Agent Masters')
        ordering = ['agent_name']
        indexes = [
            models.Index(fields=['agent_name']),
            models.Index(fields=['status']),
            models.Index(fields=['area_region']),
        ]

    def __str__(self):
        return f"{self.agent_name} ({self.area_region or 'General'})"
