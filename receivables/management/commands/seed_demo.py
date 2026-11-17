from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from masters.models import CustomerMaster, AgentMaster, CustomerStatus, AgentStatus, BillingCycle
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
from receivables import services


class Command(BaseCommand):
    help = 'Seeds initial demonstration data for Malik Brothers Multan Receivables'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Seeding demo data..."))
        User = get_user_model()
        today = timezone.localdate()

        # 1. Setup Roles (Groups)
        roles = ['Admin', 'Receiving Clerk', 'Delivery Clerk', 'Accounts Clerk', 'Manager']
        groups = {}
        for r in roles:
            g, _ = Group.objects.get_or_create(name=r)
            groups[r] = g

        demo_pass = "Malik123!"

        users_meta = [
            ('admin', 'Admin User', 'Admin', True, True),
            ('receiving_clerk', 'Bashir Ahmed', 'Receiving Clerk', False, False),
            ('delivery_clerk', 'Farooq Sheikh', 'Delivery Clerk', False, False),
            ('accounts_clerk', 'Naveed Akhtar', 'Accounts Clerk', False, False),
            ('manager', 'Malik Jahangir', 'Manager', False, True),
        ]

        users = {}
        for username, full_name, role_name, is_super, is_staff in users_meta:
            u, created = User.objects.get_or_create(username=username)
            names = full_name.split(' ', 1)
            u.first_name = names[0]
            u.last_name = names[1] if len(names) > 1 else ''
            u.is_superuser = is_super
            u.is_staff = is_staff or is_super
            u.set_password(demo_pass)
            u.save()
            u.groups.clear()
            u.groups.add(groups[role_name])
            users[username] = u

        admin_user = users['admin']

        # 2. Setup 6 Regular Customers
        customers_data = [
            {
                'name': 'Al-Madina Traders',
                'contact': '0300-9876541',
                'alt': '061-4567891',
                'address': 'Shop 14, Bosan Road Market, Multan',
                'area': 'Bosan Road',
                'cycle': BillingCycle.WEEKLY,
                'limit': Decimal('50000.00'),
                'hold': False,
            },
            {
                'name': 'Multan Fabrics & Sons',
                'contact': '0301-4455662',
                'alt': '061-3322112',
                'address': 'Chowk Hussain Agahi, Cloth Market, Multan',
                'area': 'Hussain Agahi',
                'cycle': BillingCycle.MONTH_END,
                'limit': Decimal('100000.00'),
                'hold': False,
            },
            {
                'name': 'Khanewal Agro Goods',
                'contact': '0302-8877663',
                'alt': '',
                'address': 'Near Dry Port, Khanewal Road, Multan',
                'area': 'Khanewal Road',
                'cycle': BillingCycle.DAILY,
                'limit': None,
                'hold': True,  # ON HOLD
            },
            {
                'name': 'Chenab Industrial Works',
                'contact': '0303-1122445',
                'alt': '061-5544331',
                'address': 'Plot 45-B, Industrial Estate Phase 1, Multan',
                'area': 'Industrial Estate',
                'cycle': BillingCycle.MONTH_END,
                'limit': Decimal('25000.00'),  # Strict credit limit
                'hold': False,
            },
            {
                'name': 'Rehman Auto Parts',
                'contact': '0304-9988776',
                'alt': '',
                'address': 'Shop 8, Auto Market, Vehari Chowk, Multan',
                'area': 'Vehari Chowk',
                'cycle': BillingCycle.WEEKLY,
                'limit': None,
                'hold': False,
            },
            {
                'name': 'Qasim Iron & Steel Mart',
                'contact': '0305-6677889',
                'alt': '061-7788990',
                'address': 'Main Market, Shah Rukn-e-Alam Colony, Multan',
                'area': 'Shah Rukn-e-Alam',
                'cycle': BillingCycle.WEEKLY,
                'limit': Decimal('75000.00'),
                'hold': False,
            },
        ]

        customers = []
        for c in customers_data:
            cust, _ = CustomerMaster.objects.get_or_create(
                customer_name=c['name'],
                defaults={
                    'contact_number': c['contact'],
                    'alternate_contact': c['alt'],
                    'address': c['address'],
                    'delivery_address': c['address'],
                    'area_region': c['area'],
                    'billing_cycle': c['cycle'],
                    'credit_limit': c['limit'],
                    'hold_flag': c['hold'],
                    'created_by': admin_user,
                    'status': CustomerStatus.ACTIVE,
                }
            )
            customers.append(cust)

        # 3. Setup 4 Agents
        agents_data = [
            ('Tariq Mehmood', '0301-7788991', 'Bosan Road'),
            ('Rashid Minhas', '0302-5566772', 'Hussain Agahi'),
            ('Zulfiqar Ali', '0303-3344553', 'Industrial Estate'),
            ('Imran Shah', '0304-1122334', 'Vehari Chowk'),
        ]

        agents = []
        for name, phone, area in agents_data:
            ag, _ = AgentMaster.objects.get_or_create(
                agent_name=name,
                defaults={
                    'contact_number': phone,
                    'area_region': area,
                    'status': AgentStatus.ACTIVE,
                    'created_by': admin_user,
                }
            )
            agents.append(ag)

        # 4. Create ~25 Consignments across different states
        # Clean existing demo consignments to avoid duplicates if re-run
        Consignment.objects.filter(builty_no__startswith='DEMO-').delete()

        raw_consignments = [
            # Open, Not Delivered (fresh arrivals, various dates)
            ('DEMO-1001', 'Regular', customers[0], 'Deliver at Address', Decimal('12000.00'), Decimal('2000.00'), GoodsCondition.RECEIVED_OK, 1, 'Not Delivered', Decimal('0.00'), None, None),
            ('DEMO-1002', 'Regular', customers[1], 'Deliver at Address', Decimal('15000.00'), Decimal('5000.00'), GoodsCondition.RECEIVED_OK, 2, 'Not Delivered', Decimal('0.00'), None, None),
            ('DEMO-1003', 'Walk-in', None, 'Collect from Office', Decimal('4500.00'), Decimal('1000.00'), GoodsCondition.RECEIVED_OK, 0, 'Not Delivered', Decimal('0.00'), None, None),
            ('DEMO-1004', 'Regular', customers[3], 'Deliver at Address', Decimal('8000.00'), Decimal('0.00'), GoodsCondition.RECEIVED_OK, 3, 'Not Delivered', Decimal('0.00'), None, None),
            ('DEMO-1005', 'Walk-in', None, 'Collect from Office', Decimal('6000.00'), Decimal('2000.00'), GoodsCondition.RECEIVED_OK, 4, 'Not Delivered', Decimal('0.00'), None, None),
            ('DEMO-1006', 'Regular', customers[4], 'Deliver at Address', Decimal('9500.00'), Decimal('1500.00'), GoodsCondition.RECEIVED_OK, 5, 'Not Delivered', Decimal('0.00'), None, None),

            # Delivered, Partially Paid via Counter (Remaining balance open)
            ('DEMO-1007', 'Regular', customers[0], 'Deliver at Address', Decimal('10000.00'), Decimal('1000.00'), GoodsCondition.RECEIVED_OK, 7, 'Delivered', Decimal('4000.00'), 'Delivery Counter', None),
            ('DEMO-1008', 'Regular', customers[1], 'Deliver at Address', Decimal('18000.00'), Decimal('3000.00'), GoodsCondition.RECEIVED_OK, 8, 'Delivered', Decimal('5000.00'), 'Delivery Counter', None),
            ('DEMO-1009', 'Walk-in', None, 'Collect from Office', Decimal('7000.00'), Decimal('2000.00'), GoodsCondition.RECEIVED_OK, 6, 'Delivered', Decimal('2500.00'), 'Delivery Counter', None),
            ('DEMO-1010', 'Regular', customers[5], 'Deliver at Address', Decimal('22000.00'), Decimal('4000.00'), GoodsCondition.RECEIVED_OK, 9, 'Delivered', Decimal('6000.00'), 'Delivery Counter', None),

            # Delivered, Partially Paid via Agent (Remaining balance open)
            ('DEMO-1011', 'Regular', customers[0], 'Deliver at Address', Decimal('14000.00'), Decimal('2000.00'), GoodsCondition.RECEIVED_OK, 10, 'Delivered', Decimal('4000.00'), 'Agent', agents[0]),
            ('DEMO-1012', 'Regular', customers[1], 'Deliver at Address', Decimal('25000.00'), Decimal('5000.00'), GoodsCondition.RECEIVED_OK, 11, 'Delivered', Decimal('7000.00'), 'Agent', agents[1]),
            ('DEMO-1013', 'Regular', customers[3], 'Deliver at Address', Decimal('16000.00'), Decimal('3000.00'), GoodsCondition.RECEIVED_OK, 12, 'Delivered', Decimal('5000.00'), 'Agent', agents[2]),
            ('DEMO-1014', 'Regular', customers[4], 'Deliver at Address', Decimal('11000.00'), Decimal('1000.00'), GoodsCondition.RECEIVED_OK, 13, 'Delivered', Decimal('3000.00'), 'Agent', agents[3]),

            # Delivered, Fully Paid -> Closed (Receivable = 0)
            ('DEMO-1015', 'Regular', customers[0], 'Deliver at Address', Decimal('10000.00'), Decimal('2000.00'), GoodsCondition.RECEIVED_OK, 14, 'Delivered', Decimal('8000.00'), 'Delivery Counter', None),
            ('DEMO-1016', 'Walk-in', None, 'Collect from Office', Decimal('5000.00'), Decimal('1000.00'), GoodsCondition.RECEIVED_OK, 15, 'Delivered', Decimal('4000.00'), 'Delivery Counter', None),
            ('DEMO-1017', 'Regular', customers[1], 'Deliver at Address', Decimal('20000.00'), Decimal('5000.00'), GoodsCondition.RECEIVED_OK, 16, 'Delivered', Decimal('15000.00'), 'Agent', agents[1]),
            ('DEMO-1018', 'Regular', customers[4], 'Deliver at Address', Decimal('8500.00'), Decimal('2500.00'), GoodsCondition.RECEIVED_OK, 17, 'Delivered', Decimal('6000.00'), 'Delivery Counter', None),
            ('DEMO-1019', 'Walk-in', None, 'Collect from Office', Decimal('12000.00'), Decimal('4000.00'), GoodsCondition.RECEIVED_OK, 18, 'Delivered', Decimal('8000.00'), 'Agent', agents[3]),

            # Lost / Damaged Pending Form 4 Settlement (Open status)
            ('DEMO-1020', 'Regular', customers[0], 'Deliver at Address', Decimal('13000.00'), Decimal('3000.00'), GoodsCondition.DAMAGED, 4, 'Not Delivered', Decimal('0.00'), None, None),
            ('DEMO-1021', 'Regular', customers[3], 'Deliver at Address', Decimal('9000.00'), Decimal('2000.00'), GoodsCondition.LOST, 5, 'Not Delivered', Decimal('0.00'), None, None),
            ('DEMO-1022', 'Walk-in', None, 'Collect from Office', Decimal('6500.00'), Decimal('1500.00'), GoodsCondition.DAMAGED, 3, 'Not Delivered', Decimal('0.00'), None, None),

            # Lost / Damaged with Completed Form 4 Settlement -> Closed
            ('DEMO-1023', 'Regular', customers[1], 'Deliver at Address', Decimal('14000.00'), Decimal('2000.00'), GoodsCondition.DAMAGED, 10, 'Not Delivered', Decimal('0.00'), None, None),
            ('DEMO-1024', 'Regular', customers[5], 'Deliver at Address', Decimal('16000.00'), Decimal('4000.00'), GoodsCondition.LOST, 12, 'Not Delivered', Decimal('0.00'), None, None),
            ('DEMO-1025', 'Walk-in', None, 'Collect from Office', Decimal('8000.00'), Decimal('2000.00'), GoodsCondition.DAMAGED, 8, 'Not Delivered', Decimal('0.00'), None, None),
        ]

        created_count = 0
        for item in raw_consignments:
            b_no, c_type, cust, del_mode, total, advance, cond, days_ago, del_status, pay_amt, pay_via, ag_obj = item
            rec_date = today - timedelta(days=days_ago)

            c_name = cust.customer_name if cust else f"Walk-in Customer ({b_no[-4:]})"
            c_phone = cust.contact_number if cust else "0312-3456789"
            c_addr = cust.delivery_address if (cust and del_mode == 'Deliver at Address') else ''

            init_balance = total - advance

            consignment = Consignment.objects.create(
                form_no=services.generate_form_no(),
                received_date=rec_date,
                builty_no=b_no,
                customer_builty_no=f"REF-{b_no}",
                customer_type=c_type,
                customer=cust,
                customer_name=c_name,
                contact_number=c_phone,
                delivery_mode=del_mode,
                delivery_address=c_addr,
                total_amount=total,
                advance_received=advance,
                receivable_amount=init_balance,
                goods_condition=cond,
                delivery_status=del_status,
                delivered_date=(rec_date + timedelta(days=1)) if del_status == 'Delivered' else None,
                status=ConsignmentStatus.OPEN,
                created_by=admin_user,
            )

            # Apply payment receipt if any
            if pay_amt > Decimal('0.00'):
                r_date = rec_date + timedelta(days=1)
                PaymentReceipt.objects.create(
                    consignment=consignment,
                    receipt_date=r_date,
                    amount_received=pay_amt,
                    received_via=pay_via,
                    agent=ag_obj,
                    payment_mode=PaymentMode.CASH,
                    receivable_after=init_balance - pay_amt,
                    created_by=admin_user,
                )
                consignment.receivable_amount = max(Decimal('0.00'), init_balance - pay_amt)
                if consignment.receivable_amount == Decimal('0.00') and consignment.delivery_status == 'Delivered':
                    consignment.status = ConsignmentStatus.CLOSED
                consignment.save()

            # Apply settlement if in items 1023, 1024, 1025
            if b_no in ['DEMO-1023', 'DEMO-1024', 'DEMO-1025']:
                LossDamageSettlement.objects.create(
                    consignment=consignment,
                    goods_condition=cond,
                    amount_paid_to_customer=Decimal('3500.00'),
                    settlement_date=rec_date + timedelta(days=2),
                    remarks=f"Compensated for {cond} goods approved by Manager.",
                    created_by=users['manager'],
                )
                consignment.status = ConsignmentStatus.CLOSED
                consignment.save()

            created_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded demo data: 5 users/roles, 6 customers, 4 agents, {created_count} consignments."))

