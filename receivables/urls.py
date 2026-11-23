from django.urls import path
from . import views

app_name = 'receivables'

urlpatterns = [
    # Consignment Receiving as root and default view
    path('', views.form1_receiving, name='form1_receiving'),
    path('form1/', views.form1_receiving, name='form1_receiving_direct'),
    path('form1/update-status/', views.update_builty_status, name='update_builty_status'),
    path('audit-logs/', views.audit_logs_report, name='audit_logs_report'),
    path('form1/customer-details/', views.htmx_form1_customer_details, name='htmx_form1_customer_details'),
    path('form1/calc-balance/', views.htmx_form1_balance_calc, name='htmx_form1_balance_calc'),

    # Backend routes preserved
    path('dashboard/', views.dashboard, name='dashboard'),
    path('form2/', views.form2_delivery, name='form2_delivery'),
    path('form2/lookup/', views.htmx_form2_lookup, name='htmx_form2_lookup'),
    path('form2/calc-closing/', views.htmx_form2_calc_closing, name='htmx_form2_calc_closing'),
    path('form3/', views.form3_recovery, name='form3_recovery'),
    path('form3/lookup/', views.htmx_form3_lookup, name='htmx_form3_lookup'),
    path('form3/calc-closing/', views.htmx_form3_calc_closing, name='htmx_form3_calc_closing'),
    path('form4/', views.form4_settlement, name='form4_settlement'),
    path('form4/lookup/', views.htmx_form4_lookup, name='htmx_form4_lookup'),
    path('reports/open-builties/', views.report_open_builties, name='report_open_builties'),
    path('reports/customer-outstanding/', views.report_customer_outstanding, name='report_customer_outstanding'),
    path('reports/agent-outstanding/', views.report_agent_outstanding, name='report_agent_outstanding'),
]
