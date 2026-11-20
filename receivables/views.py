import csv
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Sum, Count, Q, F
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.utils.translation import gettext as _

from masters.models import CustomerMaster, AgentMaster, CustomerStatus, AgentStatus
from receivables.models import (
    Consignment,
    PaymentReceipt,
    LossDamageSettlement,
    GoodsCondition,
    DeliveryStatus,
    ConsignmentStatus,
    CustomerCategory,
    DeliveryMode,
    PaymentMode,
    ReceivedVia,
)
from receivables.permissions import role_required
from receivables import services


@login_required
def dashboard(request):
    """
    Main KPI Dashboard with collections chart, area chart, and 10 oldest unpaid builties.
    Accessible to all authorized roles.
    """
    today = timezone.localdate()

    # KPI 1: Total Outstanding
    total_outstanding = (
        Consignment.objects.filter(status=ConsignmentStatus.OPEN)
        .aggregate(Sum('receivable_amount'))['receivable_amount__sum']
        or Decimal('0.00')
    )

    # KPI 2: Collected Today
    collected_today = (
        PaymentReceipt.objects.filter(receipt_date=today)
        .aggregate(Sum('amount_received'))['amount_received__sum']
        or Decimal('0.00')
    )

    # KPI 3: Builties Received Today
    builties_today = Consignment.objects.filter(received_date=today).count()

    # KPI 4: Open Builties Count
    open_builties_count = Consignment.objects.filter(status=ConsignmentStatus.OPEN).count()

    # KPI 5: Lost/Damaged Pending
    lost_damaged_pending = Consignment.objects.filter(
        status=ConsignmentStatus.OPEN,
        goods_condition__in=[GoodsCondition.DAMAGED, GoodsCondition.LOST]
    ).count()

    # 14-day collections bar chart data
    chart_dates = []
    chart_collections = []
    for i in range(13, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime('%b %d')
        chart_dates.append(day_str)
        day_sum = (
            PaymentReceipt.objects.filter(receipt_date=day)
            .aggregate(Sum('amount_received'))['amount_received__sum']
            or Decimal('0.00')
        )
        chart_collections.append(float(day_sum))

    # Outstanding by Area chart data
    open_consignments = Consignment.objects.filter(status=ConsignmentStatus.OPEN)
    area_data = {}
    for c in open_consignments.select_related('customer'):
        area = 'Walk-in / Direct'
        if c.customer and c.customer.area_region:
            area = c.customer.area_region
        area_data[area] = area_data.get(area, Decimal('0.00')) + c.receivable_amount

    # Top 6 areas sorted by outstanding
    sorted_areas = sorted(area_data.items(), key=lambda x: x[1], reverse=True)[:6]
    area_labels = [k for k, _ in sorted_areas]
    area_values = [float(v) for _, v in sorted_areas]

    # 10 Oldest Unpaid Builties
    oldest_unpaid = (
        Consignment.objects.filter(status=ConsignmentStatus.OPEN, receivable_amount__gt=Decimal('0.00'))
        .order_by('received_date', 'form_no')[:10]
    )

    context = {
        'total_outstanding': total_outstanding,
        'collected_today': collected_today,
        'builties_today': builties_today,
        'open_builties_count': open_builties_count,
        'lost_damaged_pending': lost_damaged_pending,
        'chart_dates': chart_dates,
        'chart_collections': chart_collections,
        'area_labels': area_labels,
        'area_values': area_values,
        'oldest_unpaid': oldest_unpaid,
    }
    return render(request, 'receivables/dashboard.html', context)


# ==============================================================================
# FORM 1: CONSIGNMENT RECEIVING
# ==============================================================================

def _safe_balance(data):
    try:
        t = Decimal(data.get('total_amount') or '0')
        a = Decimal(data.get('advance_received') or '0')
        l = Decimal(data.get('loading_charges') or '0')
        g = Decimal(data.get('godam_charges') or '0')
    except Exception:
        return Decimal('0.00')
    return max(Decimal('0.00'), t + l + g - a)


def form1_receiving(request):
    """
    Form 1: Consignment Receiving.
    """
    customers = CustomerMaster.objects.filter(status=CustomerStatus.ACTIVE).order_by('customer_name')
    success_consignment = None
    credit_warning = None
    form_data = {}
    errors = {}

    if request.method == 'POST':
        builty_no = request.POST.get('builty_no', '').strip()
        customer_builty_no = request.POST.get('customer_builty_no', '').strip()
        customer_type = request.POST.get('customer_type', CustomerCategory.REGULAR)
        customer_id = request.POST.get('customer_id')
        customer_name = request.POST.get('customer_name', '').strip()
        contact_number = request.POST.get('contact_number', '').strip()
        delivery_mode = request.POST.get('delivery_mode', DeliveryMode.COLLECT_FROM_OFFICE)
        delivery_address = request.POST.get('delivery_address', '').strip()
        total_amount = request.POST.get('total_amount', '0').strip()
        advance_received = request.POST.get('advance_received', '0').strip()
        loading_charges = request.POST.get('loading_charges', '0').strip()
        godam_charges = request.POST.get('godam_charges', '0').strip()
        goods_condition = request.POST.get('goods_condition', GoodsCondition.RECEIVED_OK)
        remarks = request.POST.get('remarks', '').strip()

        form_data = {
            'builty_no': builty_no,
            'customer_builty_no': customer_builty_no,
            'customer_type': customer_type,
            'customer_id': customer_id,
            'customer_name': customer_name,
            'contact_number': contact_number,
            'delivery_mode': delivery_mode,
            'delivery_address': delivery_address,
            'total_amount': total_amount,
            'advance_received': advance_received,
            'loading_charges': loading_charges,
            'godam_charges': godam_charges,
            'goods_condition': goods_condition,
            'remarks': remarks,
        }

        try:
            consignment, warning = services.create_consignment(
                builty_no=builty_no,
                customer_type=customer_type,
                total_amount=Decimal(total_amount or '0'),
                advance_received=Decimal(advance_received or '0'),
                loading_charges=Decimal(loading_charges or '0'),
                godam_charges=Decimal(godam_charges or '0'),
                goods_condition=goods_condition,
                delivery_mode=delivery_mode,
                customer_id=int(customer_id) if (customer_type == CustomerCategory.REGULAR and customer_id) else None,
                customer_name=customer_name,
                contact_number=contact_number,
                delivery_address=delivery_address,
                customer_builty_no=customer_builty_no,
                remarks=remarks,
                user=request.user if request.user.is_authenticated else None,
            )
            success_consignment = consignment
            credit_warning = warning
            messages.success(request, _("Builty '%(b_no)s' successfully received!") % {'b_no': consignment.builty_no})
            # Clear form_data on success
            form_data = {}
        except ValidationError as e:
            errors['non_field'] = e.message if hasattr(e, 'message') else str(e)
        except Exception as e:
            errors['non_field'] = str(e)

    # Existing Builties Search & List
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    delivery_filter = request.GET.get('delivery_status', '').strip()

    builties = Consignment.objects.all().order_by('-received_date', '-form_no')
    if query:
        builties = builties.filter(
            Q(form_no__icontains=query) |
            Q(builty_no__icontains=query) |
            Q(customer_builty_no__icontains=query) |
            Q(customer_name__icontains=query) |
            Q(contact_number__icontains=query)
        )
    if status_filter:
        builties = builties.filter(status=status_filter)
    if delivery_filter:
        builties = builties.filter(delivery_status=delivery_filter)

    paginator = Paginator(builties, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'customers': customers,
        'customer_categories': CustomerCategory.choices,
        'delivery_modes': DeliveryMode.choices,
        'goods_conditions': GoodsCondition.choices,
        'success_consignment': success_consignment,
        'credit_warning': credit_warning,
        'form_data': form_data,
        'errors': errors,
        'init_type': form_data.get('customer_type') or CustomerCategory.REGULAR,
        'init_mode': form_data.get('delivery_mode') or DeliveryMode.DELIVER_AT_ADDRESS,
        'init_customer': CustomerMaster.objects.filter(pk=form_data['customer_id']).first() if form_data.get('customer_id') else None,
        'init_balance': _safe_balance(form_data),
        # Builties list context
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
        'delivery_filter': delivery_filter,
        'status_choices': ConsignmentStatus.choices,
        'delivery_statuses': DeliveryStatus.choices,
        'total_builties_count': Consignment.objects.count(),
        'total_found': builties.count(),
    }
    return render(request, 'receivables/form1_receiving.html', context)


def builty_search(request):
    """
    Search existing builties (read-only): by Receiving Ref No., Karachi builty no.,
    customer builty ref, customer name or contact number.
    """
    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    delivery_filter = request.GET.get('delivery_status', '').strip()

    builties = Consignment.objects.all().order_by('-received_date', '-form_no')
    if query:
        builties = builties.filter(
            Q(form_no__icontains=query) |
            Q(builty_no__icontains=query) |
            Q(customer_builty_no__icontains=query) |
            Q(customer_name__icontains=query) |
            Q(contact_number__icontains=query)
        )
    if status_filter:
        builties = builties.filter(status=status_filter)
    if delivery_filter:
        builties = builties.filter(delivery_status=delivery_filter)

    page_obj = Paginator(builties, 15).get_page(request.GET.get('page'))
    context = {
        'page_obj': page_obj,
        'query': query,
        'status_filter': status_filter,
        'delivery_filter': delivery_filter,
        'status_choices': ConsignmentStatus.choices,
        'delivery_statuses': DeliveryStatus.choices,
        'total_found': builties.count(),
    }
    return render(request, 'receivables/builty_search.html', context)


def htmx_form1_customer_details(request):
    """
    HTMX partial: dynamically renders fields when customer is selected or customer type toggled.
    """
    customer_type = request.GET.get('customer_type', CustomerCategory.REGULAR)
    customer_id = request.GET.get('customer_id')
    delivery_mode = request.GET.get('delivery_mode', DeliveryMode.DELIVER_AT_ADDRESS)

    customer = None
    credit_warning = None
    outstanding = Decimal('0.00')

    if customer_type == CustomerCategory.REGULAR and customer_id:
        try:
            customer = CustomerMaster.objects.get(pk=customer_id)
            outstanding = customer.get_total_outstanding()
            has_warn, warn_msg = services.check_customer_credit(customer)
            if has_warn:
                credit_warning = warn_msg
        except CustomerMaster.DoesNotExist:
            pass

    customers = CustomerMaster.objects.filter(status=CustomerStatus.ACTIVE).order_by('customer_name')
    context = {
        'customer_type': customer_type,
        'customer': customer,
        'customers': customers,
        'delivery_mode': delivery_mode,
        'credit_warning': credit_warning,
        'outstanding': outstanding,
    }
    return render(request, 'receivables/partials/form1_customer_fields.html', context)


def htmx_form1_balance_calc(request):
    """
    HTMX partial: recalculates balance receivable live.
    Balance = Freight + Loading/Unloading + Godam - Advance.
    """
    def _dec(name):
        try:
            return Decimal(request.GET.get(name, '0') or '0')
        except Exception:
            return Decimal('0.00')

    total = _dec('total_amount')
    advance = _dec('advance_received')
    loading = _dec('loading_charges')
    godam = _dec('godam_charges')

    balance = max(Decimal('0.00'), total + loading + godam - advance)
    error = None
    if advance > total:
        error = _("Advance cannot exceed Total Freight Charges.")

    context = {
        'total': total,
        'advance': advance,
        'loading': loading,
        'godam': godam,
        'balance': balance,
        'error': error,
    }
    return render(request, 'receivables/partials/form1_balance_display.html', context)


# ==============================================================================
# FORM 2: DELIVERY AND PAYMENT
# ==============================================================================

@login_required
@role_required(['Admin', 'Delivery Clerk'])
def form2_delivery(request):
    """
    Form 2: Delivery and Payment.
    """
    success_data = None
    errors = {}
    form_no_input = request.GET.get('form_no', '').strip()

    if request.method == 'POST':
        form_no = request.POST.get('form_no', '').strip()
        delivery_status = request.POST.get('delivery_status')
        amount_collected = request.POST.get('amount_collected', '0').strip()
        payment_mode = request.POST.get('payment_mode', PaymentMode.CASH)

        try:
            consignment, receipt = services.process_delivery_and_payment(
                form_no=form_no,
                delivery_status=delivery_status,
                amount_collected=Decimal(amount_collected or '0'),
                payment_mode=payment_mode,
                user=request.user,
            )
            success_data = {
                'consignment': consignment,
                'receipt': receipt,
                'closing_balance': consignment.receivable_amount,
            }
            messages.success(request, _("Delivery status and payment updated successfully for '%(form_no)s'!") % {'form_no': form_no})
        except ValidationError as e:
            errors['non_field'] = e.message if hasattr(e, 'message') else str(e)
            form_no_input = form_no
        except Exception as e:
            errors['non_field'] = str(e)
            form_no_input = form_no

    context = {
        'form_no_input': form_no_input,
        'success_data': success_data,
        'errors': errors,
        'delivery_statuses': DeliveryStatus.choices,
        'payment_modes': PaymentMode.choices,
    }
    return render(request, 'receivables/form2_delivery.html', context)


@login_required
@role_required(['Admin', 'Delivery Clerk'])
def htmx_form2_lookup(request):
    """
    HTMX partial: fetches consignment details when user enters Reference No.
    """
    form_no = request.GET.get('form_no', '').strip()
    consignment = None
    opening_balance = Decimal('0.00')
    error = None

    if form_no:
        try:
            consignment = Consignment.objects.get(form_no=form_no)
            opening_balance = services.calculate_opening_balance(consignment)
        except Consignment.DoesNotExist:
            error = _("No consignment found with Reference No. '%(no)s'") % {'no': form_no}

    context = {
        'consignment': consignment,
        'opening_balance': opening_balance,
        'error': error,
        'delivery_statuses': DeliveryStatus.choices,
        'payment_modes': PaymentMode.choices,
    }
    return render(request, 'receivables/partials/form2_builty_details.html', context)


@login_required
@role_required(['Admin', 'Delivery Clerk'])
def htmx_form2_calc_closing(request):
    """
    HTMX partial: live closing balance preview as user types amount collected.
    """
    try:
        opening = Decimal(request.GET.get('opening_balance', '0') or '0')
    except Exception:
        opening = Decimal('0.00')

    try:
        collected = Decimal(request.GET.get('amount_collected', '0') or '0')
    except Exception:
        collected = Decimal('0.00')

    closing = opening - collected
    error = None
    if collected > opening:
        error = _("Amount collected cannot exceed Opening Balance (Rs. %(opening)s).") % {'opening': f"{opening:,.2f}"}

    context = {
        'opening_balance': opening,
        'amount_collected': collected,
        'closing_balance': max(Decimal('0.00'), closing),
        'error': error,
    }
    return render(request, 'receivables/partials/form2_closing_preview.html', context)


# ==============================================================================
# FORM 3: AGENT RECOVERY
# ==============================================================================

@login_required
@role_required(['Admin', 'Accounts Clerk'])
def form3_recovery(request):
    """
    Form 3: Agent Recovery.
    """
    agents = AgentMaster.objects.filter(status=AgentStatus.ACTIVE).order_by('agent_name')
    success_data = None
    errors = {}
    form_no_input = request.GET.get('form_no', '').strip()

    if request.method == 'POST':
        form_no = request.POST.get('form_no', '').strip()
        agent_id = request.POST.get('agent_id')
        amount_collected = request.POST.get('amount_collected', '0').strip()
        payment_mode = request.POST.get('payment_mode', PaymentMode.CASH)

        try:
            if not agent_id:
                raise ValidationError(_("Please select an agent."))
            consignment, receipt = services.process_agent_recovery(
                form_no=form_no,
                agent_id=int(agent_id),
                amount_collected=Decimal(amount_collected or '0'),
                payment_mode=payment_mode,
                user=request.user,
            )
            success_data = {
                'consignment': consignment,
                'receipt': receipt,
                'closing_balance': consignment.receivable_amount,
            }
            messages.success(request, _("Agent recovery recorded successfully for '%(form_no)s'!") % {'form_no': form_no})
        except ValidationError as e:
            errors['non_field'] = e.message if hasattr(e, 'message') else str(e)
            form_no_input = form_no
        except Exception as e:
            errors['non_field'] = str(e)
            form_no_input = form_no

    context = {
        'agents': agents,
        'form_no_input': form_no_input,
        'success_data': success_data,
        'errors': errors,
        'payment_modes': PaymentMode.choices,
    }
    return render(request, 'receivables/form3_recovery.html', context)


@login_required
@role_required(['Admin', 'Accounts Clerk'])
def htmx_form3_lookup(request):
    """
    HTMX partial: fetches consignment details for agent recovery.
    """
    form_no = request.GET.get('form_no', '').strip()
    consignment = None
    opening_balance = Decimal('0.00')
    error = None

    if form_no:
        try:
            consignment = Consignment.objects.get(form_no=form_no)
            opening_balance = services.calculate_opening_balance(consignment)
        except Consignment.DoesNotExist:
            error = _("No consignment found with Reference No. '%(no)s'") % {'no': form_no}

    agents = AgentMaster.objects.filter(status=AgentStatus.ACTIVE).order_by('agent_name')
    context = {
        'consignment': consignment,
        'opening_balance': opening_balance,
        'agents': agents,
        'error': error,
        'payment_modes': PaymentMode.choices,
    }
    return render(request, 'receivables/partials/form3_builty_details.html', context)


@login_required
@role_required(['Admin', 'Accounts Clerk'])
def htmx_form3_calc_closing(request):
    """
    HTMX partial: live closing balance preview for Form 3.
    """
    try:
        opening = Decimal(request.GET.get('opening_balance', '0') or '0')
    except Exception:
        opening = Decimal('0.00')

    try:
        collected = Decimal(request.GET.get('amount_collected', '0') or '0')
    except Exception:
        collected = Decimal('0.00')

    closing = opening - collected
    error = None
    if collected > opening:
        error = _("Amount collected cannot exceed Opening Balance (Rs. %(opening)s).") % {'opening': f"{opening:,.2f}"}

    context = {
        'opening_balance': opening,
        'amount_collected': collected,
        'closing_balance': max(Decimal('0.00'), closing),
        'error': error,
    }
    return render(request, 'receivables/partials/form3_closing_preview.html', context)


# ==============================================================================
# FORM 4: LOSS AND DAMAGE SETTLEMENT
# ==============================================================================

@login_required
@role_required(['Admin', 'Manager'])
def form4_settlement(request):
    """
    Form 4: Loss and Damage Settlement.
    """
    success_data = None
    errors = {}
    form_no_input = request.GET.get('form_no', '').strip()

    if request.method == 'POST':
        form_no = request.POST.get('form_no', '').strip()
        compensation_paid = request.POST.get('compensation_paid', '0').strip()
        remarks = request.POST.get('remarks', '').strip()

        try:
            settlement = services.process_loss_damage_settlement(
                form_no=form_no,
                compensation_paid=Decimal(compensation_paid or '0'),
                remarks=remarks,
                user=request.user if request.user.is_authenticated else None,
            )
            success_data = {
                'settlement': settlement,
                'consignment': settlement.consignment,
            }
            messages.success(request, _("Settlement recorded and builty '%(form_no)s' closed.") % {'form_no': form_no})
        except ValidationError as e:
            errors['non_field'] = e.message if hasattr(e, 'message') else str(e)
            form_no_input = form_no
        except Exception as e:
            errors['non_field'] = str(e)
            form_no_input = form_no

    context = {
        'form_no_input': form_no_input,
        'success_data': success_data,
        'errors': errors,
    }
    return render(request, 'receivables/form4_settlement.html', context)


@login_required
@role_required(['Admin', 'Manager'])
def htmx_form4_lookup(request):
    """
    HTMX partial: fetches consignment details for Form 4.
    """
    form_no = request.GET.get('form_no', '').strip()
    consignment = None
    error = None

    if form_no:
        try:
            consignment = Consignment.objects.get(form_no=form_no)
            if consignment.goods_condition not in [GoodsCondition.LOST, GoodsCondition.DAMAGED]:
                error = _("Builty '%(no)s' has condition '%(cond)s'. Form 4 accepts ONLY Lost or Damaged builties.") % {
                    'no': form_no,
                    'cond': consignment.goods_condition
                }
            elif hasattr(consignment, 'settlement') and consignment.settlement is not None:
                error = _("Builty '%(no)s' has ALREADY been settled on %(date)s.") % {
                    'no': form_no,
                    'date': consignment.settlement.settlement_date
                }
        except Consignment.DoesNotExist:
            error = _("No consignment found with Reference No. '%(no)s'") % {'no': form_no}

    context = {
        'consignment': consignment,
        'error': error,
    }
    return render(request, 'receivables/partials/form4_builty_details.html', context)


# ==============================================================================
# REPORTS & LISTS
# ==============================================================================

@login_required
@role_required(['Admin', 'Accounts Clerk', 'Manager'])
def report_open_builties(request):
    """
    Report: All Open Builties with search, filter, and CSV export.
    """
    query = request.GET.get('q', '').strip()
    delivery_filter = request.GET.get('delivery_status', '').strip()
    condition_filter = request.GET.get('goods_condition', '').strip()

    builties = Consignment.objects.filter(status=ConsignmentStatus.OPEN).order_by('-received_date', '-form_no')

    if query:
        builties = builties.filter(
            Q(form_no__icontains=query) |
            Q(builty_no__icontains=query) |
            Q(customer_name__icontains=query) |
            Q(contact_number__icontains=query)
        )

    if delivery_filter:
        builties = builties.filter(delivery_status=delivery_filter)

    if condition_filter:
        builties = builties.filter(goods_condition=condition_filter)

    # CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="open_builties.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Form No', 'Karachi Builty No', 'Received Date', 'Customer',
            'Delivery Mode', 'Total Amount', 'Advance Received',
            'Receivable Balance', 'Delivery Status', 'Goods Condition'
        ])
        for b in builties:
            writer.writerow([
                b.form_no, b.builty_no, b.received_date, b.customer_name,
                b.delivery_mode, b.total_amount, b.advance_received,
                b.receivable_amount, b.delivery_status, b.goods_condition
            ])
        return response

    paginator = Paginator(builties, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'query': query,
        'delivery_filter': delivery_filter,
        'condition_filter': condition_filter,
        'delivery_statuses': DeliveryStatus.choices,
        'goods_conditions': GoodsCondition.choices,
        'total_open_count': builties.count(),
        'total_open_receivable': builties.aggregate(Sum('receivable_amount'))['receivable_amount__sum'] or Decimal('0.00'),
    }
    return render(request, 'receivables/report_open_builties.html', context)


@login_required
@role_required(['Admin', 'Accounts Clerk', 'Manager'])
def report_customer_outstanding(request):
    """
    Report: Outstanding by Customer with search and CSV export.
    """
    query = request.GET.get('q', '').strip()
    area_filter = request.GET.get('area', '').strip()

    customers = CustomerMaster.objects.all().order_by('customer_name')
    if query:
        customers = customers.filter(
            Q(customer_name__icontains=query) |
            Q(contact_number__icontains=query)
        )
    if area_filter:
        customers = customers.filter(area_region=area_filter)

    # Calculate dynamic outstanding for each customer
    customer_list = []
    grand_total_outstanding = Decimal('0.00')

    for c in customers:
        open_consignments = c.consignments.filter(status=ConsignmentStatus.OPEN)
        open_count = open_consignments.count()
        total_outstanding = (
            open_consignments.aggregate(Sum('receivable_amount'))['receivable_amount__sum']
            or Decimal('0.00')
        )
        if total_outstanding > Decimal('0.00') or open_count > 0:
            grand_total_outstanding += total_outstanding
            customer_list.append({
                'customer': c,
                'open_count': open_count,
                'total_outstanding': total_outstanding,
                'exceeds_limit': (c.credit_limit and total_outstanding > c.credit_limit),
            })

    # CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="customer_outstanding.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Customer ID', 'Customer Name', 'Contact Number', 'Area / Region',
            'Hold Flag', 'Credit Limit', 'Open Builties', 'Total Outstanding'
        ])
        for item in customer_list:
            c = item['customer']
            writer.writerow([
                c.customer_id, c.customer_name, c.contact_number, c.area_region,
                c.hold_flag, c.credit_limit or 'None', item['open_count'], item['total_outstanding']
            ])
        return response

    paginator = Paginator(customer_list, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    distinct_areas = CustomerMaster.objects.exclude(area_region='').values_list('area_region', flat=True).distinct()

    context = {
        'page_obj': page_obj,
        'query': query,
        'area_filter': area_filter,
        'distinct_areas': distinct_areas,
        'grand_total_outstanding': grand_total_outstanding,
    }
    return render(request, 'receivables/report_customer_outstanding.html', context)


@login_required
@role_required(['Admin', 'Accounts Clerk', 'Manager'])
def report_agent_outstanding(request):
    """
    Report: Outstanding / Recovery by Agent and Area with CSV export.
    """
    agents = AgentMaster.objects.all().order_by('agent_name')
    agent_summary = []

    for agent in agents:
        # Agent collections
        total_recovered = (
            PaymentReceipt.objects.filter(agent=agent)
            .aggregate(Sum('amount_received'))['amount_received__sum']
            or Decimal('0.00')
        )
        recovery_count = PaymentReceipt.objects.filter(agent=agent).count()

        # Consignments in this agent's area
        area = agent.area_region
        area_consignments = Consignment.objects.filter(
            status=ConsignmentStatus.OPEN,
            customer__area_region=area
        ) if area else Consignment.objects.none()

        area_open_receivable = (
            area_consignments.aggregate(Sum('receivable_amount'))['receivable_amount__sum']
            or Decimal('0.00')
        )
        area_open_count = area_consignments.count()

        agent_summary.append({
            'agent': agent,
            'total_recovered': total_recovered,
            'recovery_count': recovery_count,
            'area_open_receivable': area_open_receivable,
            'area_open_count': area_open_count,
        })

    # CSV Export
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="agent_outstanding.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Agent ID', 'Agent Name', 'Contact Number', 'Area / Region',
            'Total Recovered (Rs)', 'Recovery Count', 'Area Open Balance (Rs)', 'Area Open Count'
        ])
        for row in agent_summary:
            ag = row['agent']
            writer.writerow([
                ag.agent_id, ag.agent_name, ag.contact_number, ag.area_region,
                row['total_recovered'], row['recovery_count'], row['area_open_receivable'], row['area_open_count']
            ])
        return response

    context = {
        'agent_summary': agent_summary,
    }
    return render(request, 'receivables/report_agent_outstanding.html', context)
