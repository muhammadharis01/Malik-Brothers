from decimal import Decimal
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class CustomerCategory(models.TextChoices):
    REGULAR = 'Regular', _('Regular Customer')
    WALK_IN = 'Walk-in', _('Walk-in Customer')


class DeliveryMode(models.TextChoices):
    DELIVER_AT_ADDRESS = 'Deliver at Address', _('Deliver at Address')
    COLLECT_FROM_OFFICE = 'Collect from Office', _('Collect from Office')


class GoodsCondition(models.TextChoices):
    RECEIVED_OK = 'Received OK', _('Received OK')
    DAMAGED = 'Damaged', _('Damaged')
    LOST = 'Lost', _('Lost')


class DeliveryStatus(models.TextChoices):
    NOT_DELIVERED = 'Not Delivered', _('Not Delivered')
    DELIVERED = 'Delivered', _('Delivered')


class ConsignmentStatus(models.TextChoices):
    OPEN = 'Open', _('Open')
    CLOSED = 'Closed', _('Closed')


class ReceivedVia(models.TextChoices):
    DELIVERY_COUNTER = 'Delivery Counter', _('Delivery Counter')
    AGENT = 'Agent', _('Agent')


class PaymentMode(models.TextChoices):
    CASH = 'Cash', _('Cash')
    BANK = 'Bank', _('Bank')


class Consignment(models.Model):
    form_no = models.CharField(
        max_length=20,
        primary_key=True,
        verbose_name=_('Receiving Reference No.')
    )
    received_date = models.DateField(default=timezone.localdate, verbose_name=_('Received Date'))
    builty_no = models.CharField(max_length=30, unique=True, verbose_name=_('Karachi Builty No.'))
    customer_builty_no = models.CharField(max_length=30, blank=True, verbose_name=_('Customer Builty Reference'))
    customer_type = models.CharField(
        max_length=10,
        choices=CustomerCategory.choices,
        verbose_name=_('Customer Category')
    )
    customer = models.ForeignKey(
        'masters.CustomerMaster',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='consignments',
        db_column='customer_id',
        verbose_name=_('Customer')
    )
    customer_name = models.CharField(max_length=150, verbose_name=_('Customer Name'))
    contact_number = models.CharField(max_length=30, verbose_name=_('Contact Number'))
    delivery_mode = models.CharField(
        max_length=20,
        choices=DeliveryMode.choices,
        verbose_name=_('Delivery Mode')
    )
    delivery_address = models.CharField(max_length=300, blank=True, verbose_name=_('Delivery Address'))
    total_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_('Total Freight Charges')
    )
    advance_received = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_('Advance Received')
    )
    loading_charges = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_('Loading/Unloading Charges')
    )
    godam_charges = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_('Godam Charges')
    )
    receivable_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name=_('Balance Receivable')
    )
    goods_condition = models.CharField(
        max_length=20,
        choices=GoodsCondition.choices,
        default=GoodsCondition.RECEIVED_OK,
        verbose_name=_('Goods Condition at Receipt')
    )
    delivery_status = models.CharField(
        max_length=15,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.NOT_DELIVERED,
        verbose_name=_('Delivery Status')
    )
    delivered_date = models.DateField(null=True, blank=True, verbose_name=_('Delivered Date'))
    status = models.CharField(
        max_length=10,
        choices=ConsignmentStatus.choices,
        default=ConsignmentStatus.OPEN,
        verbose_name=_('Builty Status')
    )
    remarks = models.CharField(max_length=300, blank=True, verbose_name=_('Remarks'))
    branch_id = models.IntegerField(default=1, verbose_name=_('Branch ID'))

    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_consignments',
        verbose_name=_('Created By')
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated At'))

    class Meta:
        db_table = 'consignment'
        verbose_name = _('Consignment')
        verbose_name_plural = _('Consignments')
        ordering = ['-received_date', '-form_no']
        indexes = [
            models.Index(fields=['form_no']),
            models.Index(fields=['builty_no']),
            models.Index(fields=['customer']),
            models.Index(fields=['status', 'delivery_status']),
            models.Index(fields=['received_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(advance_received__lte=F('total_amount')),
                name='consignment_advance_lte_total'
            ),
            models.CheckConstraint(
                condition=Q(total_amount__gte=Decimal('0.00')),
                name='consignment_total_gte_zero'
            ),
            models.CheckConstraint(
                condition=Q(advance_received__gte=Decimal('0.00')),
                name='consignment_advance_gte_zero'
            ),
            models.CheckConstraint(
                condition=Q(receivable_amount__gte=Decimal('0.00')),
                name='consignment_receivable_gte_zero'
            ),
            models.CheckConstraint(
                condition=Q(loading_charges__gte=Decimal('0.00')),
                name='consignment_loading_gte_zero'
            ),
            models.CheckConstraint(
                condition=Q(godam_charges__gte=Decimal('0.00')),
                name='consignment_godam_gte_zero'
            ),
        ]

    def __str__(self):
        return f"{self.form_no} - {self.builty_no} ({self.customer_name})"

    @property
    def gross_amount(self) -> Decimal:
        """Freight + Loading/Unloading + Godam charges: the full amount billed to the customer."""
        return self.total_amount + self.loading_charges + self.godam_charges

    @property
    def cumulative_received(self) -> Decimal:
        """Advance received + all payment receipts."""
        total_receipts = self.receipts.aggregate(models.Sum('amount_received'))['amount_received__sum'] or Decimal('0.00')
        return self.advance_received + total_receipts

    @property
    def is_flagged_for_settlement(self) -> bool:
        """Goods Condition at Receipt is Lost or Damaged."""
        return self.goods_condition in [GoodsCondition.DAMAGED, GoodsCondition.LOST]


class PaymentReceipt(models.Model):
    receipt_id = models.AutoField(primary_key=True)
    consignment = models.ForeignKey(
        Consignment,
        on_delete=models.PROTECT,
        related_name='receipts',
        db_column='form_no',
        verbose_name=_('Consignment')
    )
    receipt_date = models.DateField(default=timezone.localdate, verbose_name=_('Receipt Date'))
    amount_received = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_('Amount Received')
    )
    received_via = models.CharField(
        max_length=20,
        choices=ReceivedVia.choices,
        verbose_name=_('Received Via')
    )
    agent = models.ForeignKey(
        'masters.AgentMaster',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='receipts',
        db_column='agent_id',
        verbose_name=_('Collection Agent')
    )
    payment_mode = models.CharField(
        max_length=10,
        choices=PaymentMode.choices,
        default=PaymentMode.CASH,
        verbose_name=_('Payment Mode')
    )
    receivable_after = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_('Receivable After Receipt')
    )

    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_receipts',
        verbose_name=_('Created By')
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))

    class Meta:
        db_table = 'payment_receipt'
        verbose_name = _('Payment Receipt')
        verbose_name_plural = _('Payment Receipts')
        ordering = ['-receipt_date', '-receipt_id']
        indexes = [
            models.Index(fields=['consignment']),
            models.Index(fields=['agent']),
            models.Index(fields=['receipt_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_received__gt=Decimal('0.00')),
                name='receipt_amount_gt_zero'
            ),
        ]

    def __str__(self):
        return f"Receipt #{self.receipt_id} for {self.consignment.form_no} - Rs. {self.amount_received}"


class LossDamageSettlement(models.Model):
    settlement_id = models.AutoField(primary_key=True)
    consignment = models.OneToOneField(
        Consignment,
        on_delete=models.PROTECT,
        related_name='settlement',
        db_column='form_no',
        verbose_name=_('Consignment')
    )
    goods_condition = models.CharField(max_length=20, verbose_name=_('Goods Condition'))
    amount_paid_to_customer = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name=_('Compensation Paid')
    )
    settlement_date = models.DateField(default=timezone.localdate, verbose_name=_('Settlement Date'))
    remarks = models.CharField(max_length=300, blank=True, verbose_name=_('Remarks / Approver'))

    # Audit fields
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_settlements',
        verbose_name=_('Created By')
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))

    class Meta:
        db_table = 'loss_damage_settlement'
        verbose_name = _('Loss & Damage Settlement')
        verbose_name_plural = _('Loss & Damage Settlements')
        ordering = ['-settlement_date', '-settlement_id']
        indexes = [
            models.Index(fields=['consignment']),
            models.Index(fields=['settlement_date']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount_paid_to_customer__gte=Decimal('0.00')),
                name='settlement_amount_gte_zero'
            ),
        ]

    def __str__(self):
        return f"Settlement #{self.settlement_id} for {self.consignment.form_no} - Rs. {self.amount_paid_to_customer}"
