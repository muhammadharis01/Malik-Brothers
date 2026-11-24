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
    InboundTruckChallan,
    TruckChallanStatus,
    ChangeLog,
)


def log_change(
    action_type: str,
    truck_challan_key: str = '',
    builty_no: str = '',
    field_name: str = '',
    old_value: str = '',
    new_value: str = '',
    user=None,
    ip_address: Optional[str] = None,
) -> ChangeLog:
    """
    Creates an immutable audit log entry in the database.
    """
    audit_user = user if (user and getattr(user, 'is_authenticated', False)) else None
    return ChangeLog.objects.create(
        truck_challan_key=str(truck_challan_key or ''),
        builty_no=str(builty_no or ''),
        action_type=str(action_type),
        field_name=str(field_name or ''),
        old_value=str(old_value or ''),
        new_value=str(new_value or ''),
        user=audit_user,
        ip_address=ip_address,
    )


def get_or_create_truck_challan(
    truck_no: str,
    challan_no: str,
    no_of_builties: int,
    user=None,
    ip_address: Optional[str] = None,
    branch_id: int = 1,
) -> Tuple[InboundTruckChallan, bool]:
    """
    Looks up an existing Truck-Challan header or creates a new one.
    If already exists, returns the existing document without creating duplicates.
    """
    clean_truck = str(truck_no or '').strip().upper()
    clean_challan = str(challan_no or '').strip().upper()
    if not clean_truck:
        raise ValidationError(_("Truck No. is required."))
    if not clean_challan:
        raise ValidationError(_("Challan No. is required."))

    key = InboundTruckChallan.generate_key(clean_truck, clean_challan)
    existing = InboundTruckChallan.objects.filter(truck_challan_key=key).first()
    if existing:
        return existing, False

    try:
        expected_count = int(no_of_builties)
        if expected_count <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError(_("No. of Builties must be a positive integer greater than zero."))

    audit_user = user if (user and getattr(user, 'is_authenticated', False)) else None
    header = InboundTruckChallan.objects.create(
        truck_challan_key=key,
        truck_no=clean_truck,
        challan_no=clean_challan,
        no_of_builties=expected_count,
        status=TruckChallanStatus.PENDING,
        branch_id=branch_id,
        created_by=audit_user,
    )

    log_change(
        action_type='HEADER_CREATED',
        truck_challan_key=key,
        field_name='status',
        old_value='',
        new_value=f"Created with {expected_count} expected builties. Status: Pending",
        user=user,
        ip_address=ip_address,
    )
    return header, True


@transaction.atomic
def update_truck_challan_header(
    current_key: str,
    truck_no: str,
    challan_no: str,
    no_of_builties: int,
    user=None,
    ip_address: Optional[str] = None,
) -> InboundTruckChallan:
    """
    Updates header details if and only if NO builties have been attached yet.
    """
    header = InboundTruckChallan.objects.select_for_update().get(truck_challan_key=current_key)
    if header.is_locked:
        raise ValidationError(_("Header is locked and cannot be edited because Builties have already been entered."))

    clean_truck = str(truck_no or '').strip().upper()
    clean_challan = str(challan_no or '').strip().upper()
    if not clean_truck or not clean_challan:
        raise ValidationError(_("Both Truck No. and Challan No. are required."))

    try:
        expected_count = int(no_of_builties)
        if expected_count <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValidationError(_("No. of Builties must be greater than zero."))

    new_key = InboundTruckChallan.generate_key(clean_truck, clean_challan)
    if new_key != current_key and InboundTruckChallan.objects.filter(truck_challan_key=new_key).exists():
        raise ValidationError(_("A Truck-Challan document with key '%(k)s' already exists.") % {'k': new_key})

    old_summary = f"Key: {header.truck_challan_key}, Truck: {header.truck_no}, Challan: {header.challan_no}, Expected: {header.no_of_builties}"
    
    if new_key != current_key:
        # Primary key changed - delete old and create new with same audit
        created_by = header.created_by
        branch_id = header.branch_id
        header.delete()
        header = InboundTruckChallan.objects.create(
            truck_challan_key=new_key,
            truck_no=clean_truck,
            challan_no=clean_challan,
            no_of_builties=expected_count,
            status=TruckChallanStatus.PENDING,
            branch_id=branch_id,
            created_by=created_by,
        )
    else:
        header.truck_no = clean_truck
        header.challan_no = clean_challan
        header.no_of_builties = expected_count
        header.save()

    new_summary = f"Key: {header.truck_challan_key}, Truck: {header.truck_no}, Challan: {header.challan_no}, Expected: {header.no_of_builties}"
    log_change(
        action_type='HEADER_UPDATED',
        truck_challan_key=header.truck_challan_key,
        field_name='header_fields',
        old_value=old_summary,
        new_value=new_summary,
        user=user,
        ip_address=ip_address,
    )
    return header


@transaction.atomic
def update_in_transit_status(
    form_no: str,
    new_goods_condition: str,
    user=None,
    ip_address: Optional[str] = None,
) -> Consignment:
    """
    Section 8: Updating Status of In-Transit Builties.
    When goods physically arrive, user can open the builty and change ONLY Goods Received Status.
    All other fields remain read-only.
    """
    consignment = Consignment.objects.select_for_update().get(form_no=form_no)
    old_condition = consignment.goods_condition
    if old_condition != GoodsCondition.IN_TRANSIT:
        raise ValidationError(_("Only Builties with 'In Transit' status can have their status updated through this action."))

    valid_targets = [GoodsCondition.RECEIVED_OK, GoodsCondition.DAMAGED, GoodsCondition.LOST]
    if new_goods_condition not in valid_targets:
        raise ValidationError(_("Invalid goods condition '%(c)s'.") % {'c': new_goods_condition})

    consignment.goods_condition = new_goods_condition
    consignment.save(update_fields=['goods_condition', 'updated_at'])

    log_change(
        action_type='STATUS_UPDATED',
        truck_challan_key=consignment.truck_challan_id or '',
        builty_no=consignment.builty_no,
        field_name='goods_condition',
        old_value=old_condition,
        new_value=new_goods_condition,
        user=user,
        ip_address=ip_address,
    )
    return consignment


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
    opening = consignment.gross_amount - consignment.advance_received - total_receipts
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
    loading_charges: Decimal = Decimal('0.00'),
    godam_charges: Decimal = Decimal('0.00'),
    goods_condition: str = GoodsCondition.RECEIVED_OK,
    delivery_mode: str = DeliveryMode.COLLECT_FROM_OFFICE,
    customer_id: Optional[int] = None,
    customer_name: Optional[str] = None,
    contact_number: Optional[str] = None,
    delivery_address: Optional[str] = None,
    customer_builty_no: Optional[str] = '',
    remarks: Optional[str] = '',
    truck_challan_key: Optional[str] = None,
    truck_no_karachi: Optional[str] = None,
    nags: Optional[int] = None,
    user=None,
    ip_address: Optional[str] = None,
    branch_id: int = 1,
) -> Tuple[Consignment, Optional[str]]:
    """
    Form 1: Consignment Receiving.
    Saves consignment, sets Delivery Status to Not Delivered, calculates initial receivable.
    Validates against header builty count if linked to a Truck-Challan.
    """
    total_amount = Decimal(str(total_amount))
    advance_received = Decimal(str(advance_received or '0.00'))
    loading_charges = Decimal(str(loading_charges or '0.00'))
    godam_charges = Decimal(str(godam_charges or '0.00'))

    if loading_charges < Decimal('0.00'):
        raise ValidationError(_("Loading/Unloading Charges cannot be negative."))
    if godam_charges < Decimal('0.00'):
        raise ValidationError(_("Godam Charges cannot be negative."))
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

    # Validate header & control limit
    header_obj = None
    if truck_challan_key:
        try:
            header_obj = InboundTruckChallan.objects.select_for_update().get(truck_challan_key=truck_challan_key)
        except InboundTruckChallan.DoesNotExist:
            raise ValidationError(_("Truck-Challan '%(k)s' not found.") % {'k': truck_challan_key})

        current_count = header_obj.builties.count()
        if current_count >= header_obj.no_of_builties:
            raise ValidationError(
                _("Control limit reached: Cannot create more than %(max)d Builties under Truck-Challan %(k)s.")
                % {'max': header_obj.no_of_builties, 'k': header_obj.truck_challan_key}
            )

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
        balance = total_amount + loading_charges + godam_charges - advance_received
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
    initial_receivable = total_amount + loading_charges + godam_charges - advance_received

    audit_user = user if (user and getattr(user, 'is_authenticated', False)) else None
    clean_nags = max(1, int(nags)) if (nags is not None and str(nags).strip() != '') else None

    consignment = Consignment.objects.create(
        form_no=form_no,
        received_date=timezone.localdate(),
        builty_no=clean_builty_no,
        customer_builty_no=customer_builty_no or '',
        truck_challan=header_obj,
        truck_no_karachi=(truck_no_karachi or '').strip().upper(),
        nags=clean_nags,
        customer_type=customer_type,
        customer=customer_obj,
        customer_name=c_name,
        contact_number=c_contact,
        delivery_mode=delivery_mode,
        delivery_address=c_address,
        total_amount=total_amount,
        advance_received=advance_received,
        loading_charges=loading_charges,
        godam_charges=godam_charges,
        receivable_amount=initial_receivable,
        goods_condition=goods_condition,
        delivery_status=DeliveryStatus.NOT_DELIVERED,
        delivered_date=None,
        status=ConsignmentStatus.OPEN,
        remarks=remarks or '',
        branch_id=branch_id,
        created_by=audit_user,
    )

    if header_obj:
        header_obj.sync_status()
        log_change(
            action_type='BUILTY_CREATED',
            truck_challan_key=header_obj.truck_challan_key,
            builty_no=clean_builty_no,
            field_name='consignment',
            old_value='',
            new_value=f"Goods Condition: {goods_condition}, Nags: {clean_nags if clean_nags is not None else '-'}, Balance: Rs. {initial_receivable:,.2f}",
            user=user,
            ip_address=ip_address,
        )

    return consignment, credit_warning


@transaction.atomic
def process_delivery_and_payment(
    form_no: str,
    delivery_status: str,
    amount_collected: Decimal = Decimal('0.00'),
    payment_mode: str = PaymentMode.CASH,
    user=None,
    ip_address: Optional[str] = None,
) -> Tuple[Consignment, Optional[PaymentReceipt]]:
    """
    Form 2: Delivery and Payment.
    Updates delivery status, records payment receipt if entered, and recomputes receivable.
    """
    try:
        consignment = Consignment.objects.select_for_update().get(form_no=form_no)
    except Consignment.DoesNotExist:
        raise ValidationError(_("Consignment with Reference No. '%(no)s' not found.") % {'no': form_no})

    old_delivery_status = consignment.delivery_status
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
        consignment.gross_amount - consignment.advance_received - total_receipts
    )

    # Rule: Builty is Closed when Delivered and receivable = 0
    if consignment.delivery_status == DeliveryStatus.DELIVERED and consignment.receivable_amount == Decimal('0.00'):
        consignment.status = ConsignmentStatus.CLOSED

    consignment.save()

    log_change(
        action_type='DELIVERY_PAYMENT',
        truck_challan_key=consignment.truck_challan_id or '',
        builty_no=consignment.builty_no,
        field_name='delivery_and_payment',
        old_value=f"Delivery: {old_delivery_status}, Balance: Rs. {opening_balance:,.2f}",
        new_value=(
            f"Delivery: {consignment.delivery_status}, Collected: Rs. {amount_collected:,.2f} ({payment_mode}), "
            f"Closing Balance: Rs. {consignment.receivable_amount:,.2f}, Status: {consignment.status}"
        ),
        user=user,
        ip_address=ip_address,
    )
    return consignment, receipt


@transaction.atomic
def process_agent_recovery(
    form_no: str,
    agent_id: int,
    amount_collected: Decimal,
    payment_mode: str = PaymentMode.CASH,
    user=None,
    ip_address: Optional[str] = None,
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
        consignment.gross_amount - consignment.advance_received - total_receipts
    )

    # Rule: Builty is Closed when Delivered and receivable = 0
    if consignment.delivery_status == DeliveryStatus.DELIVERED and consignment.receivable_amount == Decimal('0.00'):
        consignment.status = ConsignmentStatus.CLOSED

    consignment.save()

    log_change(
        action_type='AGENT_RECOVERY',
        truck_challan_key=consignment.truck_challan_id or '',
        builty_no=consignment.builty_no,
        field_name='payment_receipt',
        old_value=f"Opening Balance: Rs. {opening_balance:,.2f}",
        new_value=(
            f"Agent: {agent.agent_name}, Collected: Rs. {amount_collected:,.2f} ({payment_mode}), "
            f"Closing Balance: Rs. {consignment.receivable_amount:,.2f}, Status: {consignment.status}"
        ),
        user=user,
        ip_address=ip_address,
    )
    return consignment, receipt


@transaction.atomic
def process_loss_damage_settlement(
    form_no: str,
    compensation_paid: Decimal,
    remarks: Optional[str] = '',
    user=None,
    ip_address: Optional[str] = None,
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

    old_status = consignment.status
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

    log_change(
        action_type='SETTLEMENT_RECORDED',
        truck_challan_key=consignment.truck_challan_id or '',
        builty_no=consignment.builty_no,
        field_name='settlement',
        old_value=f"Condition: {consignment.goods_condition}, Status: {old_status}",
        new_value=(
            f"Compensation Paid: Rs. {compensation_paid:,.2f}, Status: Closed"
            + (f", Remarks: {remarks}" if remarks else "")
        ),
        user=user,
        ip_address=ip_address,
    )

    return settlement
