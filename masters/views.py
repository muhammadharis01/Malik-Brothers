from decimal import Decimal
from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum, DecimalField, Value
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.translation import gettext as _

from .models import CustomerMaster, CustomerStatus, BillingCycle


AREA_CHOICES = [
    ('', '-- Select Area / Region --'),
    ('Bosan Road', 'Bosan Road'),
    ('Hussain Agahi', 'Hussain Agahi'),
    ('Industrial Estate', 'Industrial Estate'),
    ('Khanewal Road', 'Khanewal Road'),
    ('Vehari Chowk', 'Vehari Chowk'),
    ('Shah Rukn-e-Alam', 'Shah Rukn-e-Alam'),
    ('Cantt', 'Cantt'),
    ('Gulgasht', 'Gulgasht'),
    ('Delhi Gate', 'Delhi Gate'),
    ('General / Other', 'General / Other'),
]


class CustomerForm(forms.ModelForm):
    area_region = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all',
            'placeholder': _('Area / Region (e.g. Bosan Road, Hussain Agahi)'),
            'list': 'area-options-list',
        })
    )
    hold_flag = forms.TypedChoiceField(
        label=_('Hold'),
        coerce=lambda x: str(x).lower() in ['true', '1', 'yes'],
        choices=[(False, 'No'), (True, 'Yes')],
        widget=forms.Select(attrs={
            'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all font-semibold',
        }),
        initial=False,
        required=False,
    )

    class Meta:
        model = CustomerMaster
        fields = [
            'customer_name',
            'contact_number',
            'alternate_contact',
            'address',
            'delivery_address',
            'area_region',
            'status',
            'billing_cycle',
            'credit_limit',
            'hold_flag',
        ]
        widgets = {
            'customer_name': forms.TextInput(attrs={
                'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all',
                'placeholder': _('Customer Name'),
                'autofocus': 'autofocus',
            }),
            'contact_number': forms.TextInput(attrs={
                'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all',
                'placeholder': _('Contact Number'),
            }),
            'alternate_contact': forms.TextInput(attrs={
                'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all',
                'placeholder': _('Alternate Contact (Optional)'),
            }),
            'address': forms.TextInput(attrs={
                'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all',
                'placeholder': _('Office Address'),
            }),
            'delivery_address': forms.TextInput(attrs={
                'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all',
                'placeholder': _('Delivery Address (Defaults to Address if blank)'),
            }),
            'status': forms.Select(attrs={
                'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all',
            }),
            'billing_cycle': forms.Select(attrs={
                'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all',
            }),
            'credit_limit': forms.NumberInput(attrs={
                'class': 'w-full h-12 px-4 text-lg bg-white border border-slate-300 rounded-xl focus:border-indigo-600 focus:ring-2 focus:ring-indigo-100 outline-none transition-all font-mono',
                'placeholder': _('Blank means no limit'),
                'step': '0.01',
                'min': '0',
            }),
        }


def customer_master_view(request):
    search_query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()

    customers = CustomerMaster.objects.annotate(
        outstanding=Coalesce(
            Sum('consignments__receivable_amount', filter=Q(consignments__status='Open')),
            Value(Decimal('0.00')),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    ).order_by('-customer_id')

    if search_query:
        customers = customers.filter(
            Q(customer_name__icontains=search_query) |
            Q(contact_number__icontains=search_query) |
            Q(area_region__icontains=search_query)
        )

    if status_filter:
        customers = customers.filter(status=status_filter)

    form = CustomerForm()

    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            customer = form.save(commit=False)
            if not customer.delivery_address and customer.address:
                customer.delivery_address = customer.address
            if request.user.is_authenticated:
                customer.created_by = request.user
            customer.save()
            messages.success(request, _("Customer '%(name)s' saved.") % {'name': customer.customer_name})
            return redirect('masters:customer_master')
        else:
            messages.error(request, _("Please correct the errors."))

    paginator = Paginator(customers, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'form': form,
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
        'status_choices': CustomerStatus.choices,
        'total_customers_count': CustomerMaster.objects.count(),
    }
    return render(request, 'masters/customer_master.html', context)


def customer_edit_view(request, customer_id):
    customer = get_object_or_404(CustomerMaster, pk=customer_id)

    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            messages.success(request, _("Customer '%(name)s' updated.") % {'name': customer.customer_name})
            return redirect('masters:customer_master')
        else:
            messages.error(request, _("Please correct the errors."))
    else:
        form = CustomerForm(instance=customer)

    context = {
        'form': form,
        'customer': customer,
    }
    return render(request, 'masters/customer_edit.html', context)
