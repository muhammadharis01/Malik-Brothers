from decimal import Decimal
from typing import Optional, Tuple, Dict, Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from masters.models import CustomerMaster, AgentMaster
from receivables.models import (
    Consignment,
    PaymentReceipt,
    LossDamageSettlement,
    GoodsCondition,
    DeliveryStatus,
    ConsignmentStatus,
    ReceivedVia,
    CustomerCategory,
    DeliveryMode,
    PaymentMode,
)


def generate_form_no() -> str:
    """
    Generates a unique, sequential Receiving Reference No.
    Format: MB-YYYY-XXXXXX (e.g. MB-2026-000001). Never reused.
    """
    year = timezone.localdate().year
    prefix = f"MB-{year}-"
    # Select for update to prevent race conditions during form_no generation
    last_consignment = (
        Consignment.objects.select_for_update()
        .filter(form_no__startswith=prefix)
        .order_by('-form_no')
        .first()
    )
    if last_consignment:
        try:
            last_seq = int(last_consignment.form_no.split('-')[-1])
            next_seq = last_seq + 1
        except (ValueError, IndexError):
            next_seq = 1
    else:
        next_seq = 1

    candidate = f"{prefix}{next_seq:06d}"
    # Safety loop in case of gaps or manual imports
    while Consignment.objects.filter(form_no=candidate).exists():
        next_seq += 1
        candidate = f"{prefix}{next_seq:06d}"

    return candidate


def calculate_opening_balance(consignment: Consignment) -> Decimal:
    """
    Balance receivable before any new collection:
    total_amount - advance_received - SUM(existing receipts).
    """
    total_receipts = (
        consignment.receipts.aggregate(Sum('amount_received'))['amount_received__sum']
        or Decimal('0.00')
    )
    opening = consignment.total_amount - consignment.advance_received - total_receipts
    return max(Decimal('0.00'), opening)


def check_customer_credit(
    customer: CustomerMaster,
    additional_amount: Decimal = Decimal('0.00')
) -> Tuple[bool, Optional[str]]:
    """
    Evaluates customer hold status and credit limit against total outstanding.
    Returns (has_warning, message).
    """
    if not customer:
        return False, None

    warnings = []
    if customer.hold_flag:
        warnings.append(_("Customer '%(name)s' is marked on HOLD. Credit deliveries are restricted.") % {'name': customer.customer_name})

    current_outstanding = customer.get_total_outstanding()
    projected_outstanding = current_outstanding + additional_amount

    if customer.credit_limit is not None and customer.credit_limit > Decimal('0.00'):
        if projected_outstanding > customer.credit_limit:
            warnings.append(
                _(
                    "Customer credit limit of Rs. %(limit)s will be exceeded! "
                    "Current outstanding: Rs. %(current)s. Projected outstanding: Rs. %(projected)s."
                )
                % {
                    'limit': f"{customer.credit_limit:,.2f}",
                    'current': f"{current_outstanding:,.2f}",
                    'projected': f"{projected_outstanding:,.2f}",
                }
            )

    if warnings:
        return True, " ".join(str(w) for w in warnings)
    return False, None


@transaction.atomic
def create_consignment(
    builty_no: str,
    customer_type: str,
    total_amount: Decimal,
    advance_received: Decimal = Decimal('0.00'),
    goods_condition: str = GoodsCondition.RECEIVED_OK,
    delivery_mode: str = DeliveryMode.COLLECT_FROM_OFFICE,
    customer_id: Optional[int] = None,
    customer_name: Optional[str] = None,
    contact_number: Optional[str] = None,
    delivery_address: Optional[str] = None,
    customer_builty_no: Optional[str] = '',
    remarks: Optional[str] = '',
    user=None,
    branch_id: int = 1,
) -> Tuple[Consignment, Optional[str]]:
    """
    Form 1: Consignment Receiving.
    Saves consignment, sets Delivery Status to Not Delivered, calculates initial receivable.
    """
    total_amount = Decimal(str(total_amount))
    advance_received = Decimal(str(advance_received or '0.00'))

    if total_amount < Decimal('0.00'):
        raise ValidationError(_("Total Freight Charges cannot be negative."))
    if advance_received < Decimal('0.00'):
        raise ValidationError(_("Advance Received cannot be negative."))
    if advance_received > total_amount:
        raise ValidationError(_("Advance Received cannot exceed Total Freight Charges."))

    clean_builty_no = str(builty_no).strip()
    if not clean_builty_no:
        raise ValidationError(_("Karachi Builty No. is required."))
    if Consignment.objects.filter(builty_no=clean_builty_no).exists():
        raise ValidationError(_("Karachi Builty No. '%(no)s' already exists in the system.") % {'no': clean_builty_no})

    customer_obj = None
    credit_warning = None

    if customer_type == CustomerCategory.REGULAR:
        if not customer_id:
            raise ValidationError(_("Regular customer selection is required."))
        try:
            customer_obj = CustomerMaster.objects.get(pk=customer_id)
        except CustomerMaster.DoesNotExist:
            raise ValidationError(_("Selected customer does not exist."))

        # Master values copied
        c_name = customer_obj.customer_name
        c_contact = customer_obj.contact_number
        if delivery_mode == DeliveryMode.DELIVER_AT_ADDRESS:
            c_address = customer_obj.delivery_address or customer_obj.address
        else:
            c_address = ''

        # Perform credit check for regular customer
        balance = total_amount - advance_received
        has_warning, warning_msg = check_customer_credit(customer_obj, balance)
        if has_warning:
            action = getattr(settings, 'CREDIT_CHECK_ACTION', 'WARN')
            if action == 'BLOCK':
                raise ValidationError(warning_msg)
            else:
                credit_warning = warning_msg
    else:
        # Walk-in customer
        c_name = (customer_name or '').strip()
        c_contact = (contact_number or '').strip()
        if not c_name:
            raise ValidationError(_("Customer name is required for walk-in customers."))
        if not c_contact:
            raise ValidationError(_("Contact number is required for walk-in customers."))
        if delivery_mode == DeliveryMode.DELIVER_AT_ADDRESS:
            c_address = (delivery_address or '').strip()
        else:
            c_address = ''

    form_no = generate_form_no()
    initial_receivable = total_amount - advance_received

    audit_user = user if (user and getattr(user, 'is_authenticated', False)) else None

    consignment = Consignment.objects.create(
        form_no=form_no,
        received_date=timezone.localdate(),
        builty_no=clean_builty_no,
        customer_builty_no=customer_builty_no or '',
        customer_type=customer_type,
        customer=customer_obj,
        customer_name=c_name,
        contact_number=c_contact,
        delivery_mode=delivery_mode,
        delivery_address=c_address,
        total_amount=total_amount,
        advance_received=advance_received,
        receivable_amount=initial_receivable,
        goods_condition=goods_condition,
        delivery_status=DeliveryStatus.NOT_DELIVERED,
        delivered_date=None,
        status=ConsignmentStatus.OPEN,
        remarks=remarks or '',
        branch_id=branch_id,
        created_by=audit_user,
    )

    return consignment, credit_warning


@transaction.atomic
def process_delivery_and_payment(
    form_no: str,
    delivery_status: str,
    amount_collected: Decimal = Decimal('0.00'),
    payment_mode: str = PaymentMode.CASH,
    user=None,
) -> Tuple[Consignment, Optional[PaymentReceipt]]:
    """
    Form 2: Delivery and Payment.
    Updates delivery status, records payment receipt if entered, and recomputes receivable.
    """
    try:
        consignment = Consignment.objects.select_for_update().get(form_no=form_no)
    except Consignment.DoesNotExist:
        raise ValidationError(_("Consignment with Reference No. '%(no)s' not found.") % {'no': form_no})

    opening_balance = calculate_opening_balance(consignment)
    amount_collected = Decimal(str(amount_collected or '0.00'))

    if delivery_status not in [DeliveryStatus.NOT_DELIVERED, DeliveryStatus.DELIVERED]:
        raise ValidationError(_("Invalid delivery status."))

    # Rule: In Form 2, Amount Collected is enabled only when Delivery Status is Delivered
    if delivery_status == DeliveryStatus.NOT_DELIVERED and amount_collected > Decimal('0.00'):
        raise ValidationError(_("Amount can only be collected when Delivery Status is Delivered."))

    if amount_collected < Decimal('0.00'):
        raise ValidationError(_("Amount Collected cannot be negative."))

    if amount_collected > opening_balance:
        raise ValidationError(
            _("Amount Collected (Rs. %(collected)s) cannot exceed Opening Balance (Rs. %(opening)s).")
            % {
                'collected': f"{amount_collected:,.2f}",
                'opening': f"{opening_balance:,.2f}",
            }
        )

    audit_user = user if (user and getattr(user, 'is_authenticated', False)) else None
    receipt = None
    if amount_collected > Decimal('0.00'):
        receipt = PaymentReceipt.objects.create(
            consignment=consignment,
            receipt_date=timezone.localdate(),
            amount_received=amount_collected,
            received_via=ReceivedVia.DELIVERY_COUNTER,
            agent=None,
            payment_mode=payment_mode,
            receivable_after=opening_balance - amount_collected,
            created_by=audit_user,
        )

    # Update delivery status and date
    consignment.delivery_status = delivery_status
    if delivery_status == DeliveryStatus.DELIVERED and not consignment.delivered_date:
        consignment.delivered_date = timezone.localdate()

    # Recalculate receivable from database tables
    total_receipts = (
        consignment.receipts.aggregate(Sum('amount_received'))['amount_received__sum']
        or Decimal('0.00')
    )
    consignment.receivable_amount = max(
        Decimal('0.00'),
        consignment.total_amount - consignment.advance_received - total_receipts
    )

    # Rule: Builty is Closed when Delivered and receivable = 0
    if consignment.delivery_status == DeliveryStatus.DELIVERED and consignment.receivable_amount == Decimal('0.00'):
        consignment.status = ConsignmentStatus.CLOSED

    consignment.save()
    return consignment, receipt


@transaction.atomic
def process_agent_recovery(
    form_no: str,
    agent_id: int,
    amount_collected: Decimal,
    payment_mode: str = PaymentMode.CASH,
    user=None,
) -> Tuple[Consignment, PaymentReceipt]:
    """
    Form 3: Agent Recovery.
    Records cash recovered from customer by an agent, recomputes receivable.
    """
    try:
        consignment = Consignment.objects.select_for_update().get(form_no=form_no)
    except Consignment.DoesNotExist:
        raise ValidationError(_("Consignment with Reference No. '%(no)s' not found.") % {'no': form_no})

    try:
        agent = AgentMaster.objects.get(pk=agent_id)
    except AgentMaster.DoesNotExist:
        raise ValidationError(_("Selected agent does not exist."))

    amount_collected = Decimal(str(amount_collected or '0.00'))
    opening_balance = calculate_opening_balance(consignment)

    if amount_collected <= Decimal('0.00'):
        raise ValidationError(_("Amount Collected must be greater than zero."))

    if amount_collected > opening_balance:
        raise ValidationError(
            _("Amount Collected (Rs. %(collected)s) cannot exceed Opening Balance (Rs. %(opening)s).")
            % {
                'collected': f"{amount_collected:,.2f}",
                'opening': f"{opening_balance:,.2f}",
            }
        )

    audit_user = user if (user and getattr(user, 'is_authenticated', False)) else None
    receipt = PaymentReceipt.objects.create(
        consignment=consignment,
        receipt_date=timezone.localdate(),
        amount_received=amount_collected,
        received_via=ReceivedVia.AGENT,
        agent=agent,
        payment_mode=payment_mode,
        receivable_after=opening_balance - amount_collected,
        created_by=audit_user,
    )

    # Recalculate receivable from database tables
    total_receipts = (
        consignment.receipts.aggregate(Sum('amount_received'))['amount_received__sum']
        or Decimal('0.00')
    )
    consignment.receivable_amount = max(
        Decimal('0.00'),
        consignment.total_amount - consignment.advance_received - total_receipts
    )

    # Rule: Builty is Closed when Delivered and receivable = 0
    if consignment.delivery_status == DeliveryStatus.DELIVERED and consignment.receivable_amount == Decimal('0.00'):
        consignment.status = ConsignmentStatus.CLOSED

    consignment.save()
    return consignment, receipt


@transaction.atomic
def process_loss_damage_settlement(
    form_no: str,
    compensation_paid: Decimal,
    remarks: Optional[str] = '',
    user=None,
) -> LossDamageSettlement:
    """
    Form 4: Loss and Damage Settlement.
    Only accepts Lost or Damaged builties. One settlement per consignment.
    Marks the builty Closed.
    """
    try:
        consignment = Consignment.objects.select_for_update().get(form_no=form_no)
    except Consignment.DoesNotExist:
        raise ValidationError(_("Consignment with Reference No. '%(no)s' not found.") % {'no': form_no})

    # Rule 4: Form 4 accepts only Lost or Damaged builties
    if consignment.goods_condition not in [GoodsCondition.LOST, GoodsCondition.DAMAGED]:
        raise ValidationError(
            _("Form 4 accepts only Lost or Damaged builties. This builty has condition '%(cond)s'.")
            % {'cond': consignment.goods_condition}
        )

    # Rule: One settlement per builty
    if hasattr(consignment, 'settlement') and consignment.settlement is not None:
        raise ValidationError(_("A settlement has already been saved for Reference No. '%(no)s'.") % {'no': form_no})

    compensation_paid = Decimal(str(compensation_paid or '0.00'))
    if compensation_paid < Decimal('0.00'):
        raise ValidationError(_("Compensation Paid cannot be negative."))

    audit_user = user if (user and getattr(user, 'is_authenticated', False)) else None
    settlement = LossDamageSettlement.objects.create(
        consignment=consignment,
        goods_condition=consignment.goods_condition,
        amount_paid_to_customer=compensation_paid,
        settlement_date=timezone.localdate(),
        remarks=remarks or '',
        created_by=audit_user,
    )

    # Rule 3 & 10: Builty is Closed when its settlement is saved
    consignment.status = ConsignmentStatus.CLOSED
    consignment.save()

    return settlement
