from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, Client
from django.urls import reverse

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
    InboundTruckChallan,
    TruckChallanStatus,
    ChangeLog,
)
from receivables import services


class ReceivablesWorkedExampleAndBusinessRulesTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin_user = User.objects.create_superuser(username='test_admin', password='pass123admin')

        # Create Groups
        self.receiving_group = Group.objects.create(name='Receiving Clerk')
        self.delivery_group = Group.objects.create(name='Delivery Clerk')
        self.accounts_group = Group.objects.create(name='Accounts Clerk')
        self.manager_group = Group.objects.create(name='Manager')

        # Create Clerks
        self.receiving_user = User.objects.create_user(username='clerk_rec', password='password123')
        self.receiving_user.groups.add(self.receiving_group)

        self.manager_user = User.objects.create_user(username='test_mgr', password='password123')
        self.manager_user.groups.add(self.manager_group)

        # Create regular customer
        self.customer = CustomerMaster.objects.create(
            customer_name='Premier Cotton Mills',
            contact_number='0300-1122334',
            address='Industrial Estate, Multan',
            delivery_address='Industrial Estate, Multan',
            area_region='Industrial Estate',
            credit_limit=Decimal('50000.00'),
            hold_flag=False,
            created_by=self.admin_user,
        )

        # Create Agent
        self.agent = AgentMaster.objects.create(
            agent_name='Akram Khan',
            contact_number='0301-9988776',
            area_region='Industrial Estate',
            created_by=self.admin_user,
        )

    def test_section_6_worked_example_steps_1_to_4(self):
        """
        Tests Steps 1 through 4 from Smart Solution PDF Section 6:
        Step 1: Form 1 Total 10,000, Advance 1,000, Condition Received OK -> Ref No generated, Balance 9,000
        Step 2: Form 2 Delivery Status Delivered, Collect 1,500 -> Cumulative 2,500, Closing 7,500
        Step 3: Form 3 Agent collects 1,000 -> Closing 6,500
        Step 4: Form 3 Agent collects 6,500 -> Closing 0, Builty Closed
        """
        # Step 1: Form 1 Consignment Receiving
        consignment, warning = services.create_consignment(
            builty_no='KHI-WORKED-01',
            customer_type=CustomerCategory.REGULAR,
            total_amount=Decimal('10000.00'),
            advance_received=Decimal('1000.00'),
            goods_condition=GoodsCondition.RECEIVED_OK,
            delivery_mode=DeliveryMode.DELIVER_AT_ADDRESS,
            customer_id=self.customer.customer_id,
            user=self.receiving_user,
        )
        self.assertTrue(consignment.form_no.startswith('MB-'))
        self.assertEqual(consignment.advance_received, Decimal('1000.00'))
        self.assertEqual(consignment.total_amount, Decimal('10000.00'))
        self.assertEqual(consignment.receivable_amount, Decimal('9000.00'))
        self.assertEqual(consignment.delivery_status, DeliveryStatus.NOT_DELIVERED)
        self.assertEqual(consignment.status, ConsignmentStatus.OPEN)

        # Step 2: Form 2 Delivery Status Delivered, Collect 1,500
        consignment, receipt1 = services.process_delivery_and_payment(
            form_no=consignment.form_no,
            delivery_status=DeliveryStatus.DELIVERED,
            amount_collected=Decimal('1500.00'),
            payment_mode=PaymentMode.CASH,
            user=self.admin_user,
        )
        self.assertIsNotNone(receipt1)
        self.assertEqual(receipt1.amount_received, Decimal('1500.00'))
        self.assertEqual(receipt1.received_via, ReceivedVia.DELIVERY_COUNTER)
        self.assertEqual(consignment.cumulative_received, Decimal('2500.00'))
        self.assertEqual(consignment.receivable_amount, Decimal('7500.00'))
        self.assertEqual(consignment.delivery_status, DeliveryStatus.DELIVERED)
        self.assertEqual(consignment.status, ConsignmentStatus.OPEN)

        # Step 3: Form 3 Agent collects 1,000
        consignment, receipt2 = services.process_agent_recovery(
            form_no=consignment.form_no,
            agent_id=self.agent.agent_id,
            amount_collected=Decimal('1000.00'),
            payment_mode=PaymentMode.CASH,
            user=self.admin_user,
        )
        self.assertIsNotNone(receipt2)
        self.assertEqual(receipt2.amount_received, Decimal('1000.00'))
        self.assertEqual(receipt2.received_via, ReceivedVia.AGENT)
        self.assertEqual(consignment.cumulative_received, Decimal('3500.00'))
        self.assertEqual(consignment.receivable_amount, Decimal('6500.00'))
        self.assertEqual(consignment.status, ConsignmentStatus.OPEN)

        # Step 4: Form 3 Agent collects 6,500 -> Closing 0, Builty Closed
        consignment, receipt3 = services.process_agent_recovery(
            form_no=consignment.form_no,
            agent_id=self.agent.agent_id,
            amount_collected=Decimal('6500.00'),
            payment_mode=PaymentMode.CASH,
            user=self.admin_user,
        )
        self.assertIsNotNone(receipt3)
        self.assertEqual(receipt3.amount_received, Decimal('6500.00'))
        self.assertEqual(consignment.cumulative_received, Decimal('10000.00'))
        self.assertEqual(consignment.receivable_amount, Decimal('0.00'))
        self.assertEqual(consignment.status, ConsignmentStatus.CLOSED)

    def test_section_6_worked_example_steps_5_and_6(self):
        """
        Tests Steps 5 and 6 from Smart Solution PDF Section 6:
        Step 5: Form 1 Total 8,000, Advance 2,000, Goods Condition Lost -> Balance 6,000, Flagged for Form 4
        Step 6: Form 4 Compensation Paid 3,000 -> Settlement stored, Builty Closed
        """
        # Step 5: Form 1 Consignment Receiving with Lost condition
        consignment, warning = services.create_consignment(
            builty_no='KHI-WORKED-02',
            customer_type=CustomerCategory.REGULAR,
            total_amount=Decimal('8000.00'),
            advance_received=Decimal('2000.00'),
            goods_condition=GoodsCondition.LOST,
            delivery_mode=DeliveryMode.DELIVER_AT_ADDRESS,
            customer_id=self.customer.customer_id,
            user=self.receiving_user,
        )
        self.assertEqual(consignment.total_amount, Decimal('8000.00'))
        self.assertEqual(consignment.advance_received, Decimal('2000.00'))
        self.assertEqual(consignment.receivable_amount, Decimal('6000.00'))
        self.assertTrue(consignment.is_flagged_for_settlement)
        self.assertEqual(consignment.status, ConsignmentStatus.OPEN)

        # Step 6: Form 4 Compensation Paid 3,000 -> Settlement stored, Builty Closed
        settlement = services.process_loss_damage_settlement(
            form_no=consignment.form_no,
            compensation_paid=Decimal('3000.00'),
            remarks='Approved by Branch Manager for lost cartons',
            user=self.manager_user,
        )
        self.assertIsNotNone(settlement)
        self.assertEqual(settlement.amount_paid_to_customer, Decimal('3000.00'))
        self.assertEqual(settlement.goods_condition, GoodsCondition.LOST)

        consignment.refresh_from_db()
        self.assertEqual(consignment.status, ConsignmentStatus.CLOSED)
        self.assertTrue(hasattr(consignment, 'settlement'))

    def test_duplicate_builty_no_refused(self):
        """Rule 5: Karachi Builty No. is unique. A duplicate is refused."""
        services.create_consignment(
            builty_no='KHI-UNIQUE-01',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Ali Raza',
            contact_number='0300-1234567',
            total_amount=Decimal('5000.00'),
            advance_received=Decimal('0.00'),
            user=self.receiving_user,
        )

        with self.assertRaises(ValidationError) as ctx:
            services.create_consignment(
                builty_no='KHI-UNIQUE-01',
                customer_type=CustomerCategory.WALK_IN,
                customer_name='Different Person',
                contact_number='0300-9999999',
                total_amount=Decimal('5000.00'),
                advance_received=Decimal('0.00'),
                user=self.receiving_user,
            )
        self.assertIn("already exists", str(ctx.exception))

    def test_over_collection_refused(self):
        """Rule 2 & 3: Amount collected cannot exceed the opening balance."""
        consignment, _ = services.create_consignment(
            builty_no='KHI-OVER-01',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Tariq Glass',
            contact_number='0300-5555555',
            total_amount=Decimal('5000.00'),
            advance_received=Decimal('2000.00'),
            user=self.receiving_user,
        )
        # Opening balance is 3,000. Attempting to collect 3,001 should fail
        with self.assertRaises(ValidationError) as ctx:
            services.process_delivery_and_payment(
                form_no=consignment.form_no,
                delivery_status=DeliveryStatus.DELIVERED,
                amount_collected=Decimal('3500.00'),
                user=self.admin_user,
            )
        self.assertIn("cannot exceed", str(ctx.exception).lower())

    def test_second_settlement_refused(self):
        """Rule 4: One settlement per builty. Second settlement refused."""
        consignment, _ = services.create_consignment(
            builty_no='KHI-SETTLE-01',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Zahid Traders',
            contact_number='0300-7777777',
            total_amount=Decimal('4000.00'),
            advance_received=Decimal('0.00'),
            goods_condition=GoodsCondition.DAMAGED,
            user=self.receiving_user,
        )

        services.process_loss_damage_settlement(
            form_no=consignment.form_no,
            compensation_paid=Decimal('1500.00'),
            remarks='First settlement',
            user=self.manager_user,
        )

        with self.assertRaises(ValidationError) as ctx:
            services.process_loss_damage_settlement(
                form_no=consignment.form_no,
                compensation_paid=Decimal('500.00'),
                remarks='Second settlement attempt',
                user=self.manager_user,
            )
        self.assertIn("already been saved", str(ctx.exception))

    def test_form4_rejects_ok_condition(self):
        """Form 4 accepts only Lost or Damaged builties."""
        consignment, _ = services.create_consignment(
            builty_no='KHI-OK-01',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Fine Goods',
            contact_number='0300-8888888',
            total_amount=Decimal('6000.00'),
            advance_received=Decimal('1000.00'),
            goods_condition=GoodsCondition.RECEIVED_OK,
            user=self.receiving_user,
        )

        with self.assertRaises(ValidationError) as ctx:
            services.process_loss_damage_settlement(
                form_no=consignment.form_no,
                compensation_paid=Decimal('1000.00'),
                remarks='Invalid claim',
                user=self.manager_user,
            )
        self.assertIn("only Lost or Damaged", str(ctx.exception))

    def test_advance_greater_than_total_refused(self):
        """Advance received cannot exceed Total Freight Charges."""
        with self.assertRaises(ValidationError) as ctx:
            services.create_consignment(
                builty_no='KHI-ADV-ERR',
                customer_type=CustomerCategory.WALK_IN,
                customer_name='Test',
                contact_number='0300-1111111',
                total_amount=Decimal('5000.00'),
                advance_received=Decimal('6000.00'),
                user=self.receiving_user,
            )
        self.assertIn("cannot exceed", str(ctx.exception).lower())

    def test_form2_amount_collection_disabled_when_not_delivered(self):
        """In Form 2, Amount Collected is enabled only when Delivery Status is Delivered."""
        consignment, _ = services.create_consignment(
            builty_no='KHI-NOT-DEL-01',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Test',
            contact_number='0300-2222222',
            total_amount=Decimal('4000.00'),
            advance_received=Decimal('1000.00'),
            user=self.receiving_user,
        )
        with self.assertRaises(ValidationError) as ctx:
            services.process_delivery_and_payment(
                form_no=consignment.form_no,
                delivery_status=DeliveryStatus.NOT_DELIVERED,
                amount_collected=Decimal('1500.00'),
                user=self.admin_user,
            )
        self.assertIn("only be collected when Delivery Status is Delivered", str(ctx.exception))

    def test_permission_receiving_clerk_cannot_access_form4(self):
        """Permission check: Receiving Clerk cannot open Form 4 (must be blocked)."""
        client = Client()
        client.force_login(self.receiving_user)

        response = client.get(reverse('receivables:form4_settlement'))
        # Should return 403 Forbidden
        self.assertEqual(response.status_code, 403)

    def test_form1_accessible_without_login(self):
        """Form 1 is directly accessible at root URL without any login required."""
        client = Client()
        response = client.get(reverse('receivables:form1_receiving'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Consignment Receiving")

    def test_form1_post_without_login(self):
        """Can submit Form 1 without being logged in."""
        client = Client()
        post_data = {
            'builty_no': 'KHI-NOLOGIN-01',
            'customer_type': 'Regular',
            'customer_id': str(self.customer.customer_id),
            'delivery_mode': 'Deliver at Address',
            'total_amount': '15000.00',
            'advance_received': '3000.00',
            'goods_condition': 'Received OK',
        }
        response = client.post(reverse('receivables:form1_receiving'), data=post_data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Consignment.objects.filter(builty_no='KHI-NOLOGIN-01').exists())
        c = Consignment.objects.get(builty_no='KHI-NOLOGIN-01')
        self.assertEqual(c.receivable_amount, Decimal('12000.00'))
        self.assertIsNone(c.created_by)



class Form1UiFlowTests(TestCase):
    def setUp(self):
        from masters.models import CustomerMaster
        self.customer = CustomerMaster.objects.create(
            customer_name='Flow Test Traders', contact_number='0300-0000000',
            address='Main St', area_region='Cantt')

    def test_balance_endpoint_returns_total_minus_advance(self):
        r = self.client.get('/htmx/form1/balance/', {'total_amount': '10000', 'advance_received': '1000'}) \
            if False else None
        from django.urls import reverse
        r = self.client.get(reverse('receivables:htmx_form1_balance_calc'),
                            {'total_amount': '10000', 'advance_received': '1000'})
        self.assertContains(r, '9,000.00')

    def test_page_loads_local_htmx_and_balance_container(self):
        from django.urls import reverse
        r = self.client.get(reverse('receivables:form1_receiving'))
        self.assertContains(r, 'js/htmx.min.js')
        self.assertContains(r, 'balance-display-container')

    def test_customer_fetch_fills_contact(self):
        from django.urls import reverse
        r = self.client.get(reverse('receivables:htmx_form1_customer_details'),
                            {'customer_type': 'Regular', 'customer_id': self.customer.pk,
                             'delivery_mode': 'Deliver at Address'})
        self.assertContains(r, '0300-0000000')
        self.assertContains(r, 'Main St')

    def test_save_regular_and_walkin(self):
        from django.urls import reverse
        url = reverse('receivables:form1_receiving')
        r = self.client.post(url, {
            'builty_no': 'KHI-1', 'customer_type': 'Regular', 'customer_id': self.customer.pk,
            'delivery_mode': 'Collect from Office', 'total_amount': '10000',
            'advance_received': '1000', 'goods_condition': 'Received OK'})
        self.assertContains(r, 'MB-')
        c = Consignment.objects.get(builty_no='KHI-1')
        self.assertEqual(c.receivable_amount, Decimal('9000.00'))
        r = self.client.post(url, {
            'builty_no': 'KHI-2', 'customer_type': 'Walk-in', 'customer_name': 'Ali',
            'contact_number': '0311', 'delivery_mode': 'Deliver at Address',
            'delivery_address': 'Shop 4', 'total_amount': '8000',
            'advance_received': '2000', 'goods_condition': 'Lost'})
        c = Consignment.objects.get(builty_no='KHI-2')
        self.assertEqual(c.receivable_amount, Decimal('6000.00'))
        r = self.client.post(url, {
            'builty_no': 'KHI-2', 'customer_type': 'Walk-in', 'customer_name': 'Ali',
            'contact_number': '0311', 'delivery_mode': 'Collect from Office',
            'total_amount': '10', 'advance_received': '0', 'goods_condition': 'Received OK'})
        self.assertEqual(Consignment.objects.filter(builty_no='KHI-2').count(), 1)


class ExtraChargesAndListTests(TestCase):
    def setUp(self):
        self.customer = CustomerMaster.objects.create(
            customer_name='Charge Test Co', contact_number='0300-1111111', area_region='Cantt')

    def _save(self, builty, **extra):
        data = {'builty_no': builty, 'customer_type': 'Regular', 'customer_id': self.customer.pk,
                'delivery_mode': 'Collect from Office', 'total_amount': '10000',
                'advance_received': '1000', 'goods_condition': 'Received OK'}
        data.update(extra)
        return self.client.post(reverse('receivables:form1_receiving'), data)

    def test_loading_and_godam_added_to_balance(self):
        self._save('CH-1', loading_charges='500', godam_charges='250')
        c = Consignment.objects.get(builty_no='CH-1')
        self.assertEqual(c.loading_charges, Decimal('500.00'))
        self.assertEqual(c.godam_charges, Decimal('250.00'))
        self.assertEqual(c.receivable_amount, Decimal('9750.00'))  # 10000+500+250-1000

    def test_payments_reduce_balance_including_charges(self):
        from receivables import services
        self._save('CH-2', loading_charges='500', godam_charges='250')
        c = Consignment.objects.get(builty_no='CH-2')
        c, _r = services.process_delivery_and_payment(c.form_no, 'Delivered', Decimal('1500'))
        self.assertEqual(c.receivable_amount, Decimal('8250.00'))
        c, _r = services.process_agent_recovery(c.form_no, AgentMaster.objects.create(
            agent_name='A', contact_number='1', area_region='Cantt').pk, Decimal('8250'))
        self.assertEqual(c.receivable_amount, Decimal('0.00'))
        self.assertEqual(c.status, 'Closed')

    def test_negative_charges_refused(self):
        self._save('CH-3', loading_charges='-5')
        self.assertFalse(Consignment.objects.filter(builty_no='CH-3').exists())

    def test_balance_endpoint_includes_charges(self):
        r = self.client.get(reverse('receivables:htmx_form1_balance_calc'),
                            {'total_amount': '10000', 'advance_received': '1000',
                             'loading_charges': '500', 'godam_charges': '250'})
        self.assertContains(r, '9,750.00')

    def test_customer_list_shows_outstanding_and_edit(self):
        self._save('CH-4', loading_charges='500', godam_charges='250')
        r = self.client.get(reverse('masters:customer_master'))
        self.assertContains(r, '9,750.00')
        self.assertContains(r, reverse('masters:customer_edit', args=[self.customer.pk]))
        r = self.client.get(reverse('masters:customer_edit', args=[self.customer.pk]))
        self.assertEqual(r.status_code, 200)

    def test_builty_search(self):
        self._save('SRCH-77')
        r = self.client.get(reverse('receivables:form1_receiving'), {'q': 'SRCH-77'})
        self.assertContains(r, 'SRCH-77')
        r = self.client.get(reverse('receivables:form1_receiving'), {'q': 'nomatch'})
        self.assertContains(r, 'No builties found')


class InboundTruckChallanAndAuditLogTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username='operator1', password='pass123operator')
        self.client = Client()
        self.client.force_login(self.user)

    def test_header_creation_and_key_generation(self):
        header, created = services.get_or_create_truck_challan(
            truck_no='tk-9834',
            challan_no='ch-2302',
            no_of_builties=20,
            user=self.user,
        )
        self.assertTrue(created)
        self.assertEqual(header.truck_challan_key, 'TK-9834-CH-2302')
        self.assertEqual(header.status, TruckChallanStatus.PENDING)
        self.assertEqual(header.no_of_builties, 20)

        # Audit log entry created
        self.assertTrue(ChangeLog.objects.filter(
            truck_challan_key='TK-9834-CH-2302',
            action_type='HEADER_CREATED'
        ).exists())

    def test_reopening_existing_header_does_not_duplicate(self):
        h1, created1 = services.get_or_create_truck_challan(
            truck_no='TK-1111',
            challan_no='CH-9999',
            no_of_builties=10,
            user=self.user,
        )
        self.assertTrue(created1)

        # Reopen with same truck and challan
        h2, created2 = services.get_or_create_truck_challan(
            truck_no='TK-1111',
            challan_no='CH-9999',
            no_of_builties=15,  # ignored since it exists
            user=self.user,
        )
        self.assertFalse(created2)
        self.assertEqual(h1.truck_challan_key, h2.truck_challan_key)
        self.assertEqual(InboundTruckChallan.objects.filter(truck_challan_key='TK-1111-CH-9999').count(), 1)

    def test_control_limit_on_number_of_builties(self):
        header, _ = services.get_or_create_truck_challan(
            truck_no='TK-LIMIT',
            challan_no='CH-LIMIT',
            no_of_builties=2,  # Maximum 2 builties allowed
            user=self.user,
        )

        # Builty 1
        services.create_consignment(
            builty_no='LIM-01',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Walk-in Client',
            contact_number='0300-1111111',
            total_amount=Decimal('5000.00'),
            truck_challan_key=header.truck_challan_key,
            nags=3,
            user=self.user,
        )
        header.refresh_from_db()
        self.assertEqual(header.status, TruckChallanStatus.PENDING)
        self.assertEqual(header.builties_count, 1)
        self.assertEqual(header.total_nags, 3)

        # Builty 2 (equals limit -> Complete)
        services.create_consignment(
            builty_no='LIM-02',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Walk-in Client 2',
            contact_number='0300-2222222',
            total_amount=Decimal('3000.00'),
            truck_challan_key=header.truck_challan_key,
            nags=2,
            user=self.user,
        )
        header.refresh_from_db()
        self.assertEqual(header.status, TruckChallanStatus.COMPLETE)
        self.assertEqual(header.builties_count, 2)
        self.assertEqual(header.total_nags, 5)

        # Builty 3 (exceeds limit -> blocked by validation control)
        with self.assertRaises(ValidationError) as ctx:
            services.create_consignment(
                builty_no='LIM-03',
                customer_type=CustomerCategory.WALK_IN,
                customer_name='Walk-in Client 3',
                contact_number='0300-3333333',
                total_amount=Decimal('2000.00'),
                truck_challan_key=header.truck_challan_key,
                user=self.user,
            )
        self.assertIn("Control limit reached", str(ctx.exception))

    def test_header_edit_before_and_after_builties(self):
        header, _ = services.get_or_create_truck_challan(
            truck_no='TK-EDIT',
            challan_no='CH-ORIG',
            no_of_builties=10,
            user=self.user,
        )
        # Edit allowed when 0 builties exist
        updated = services.update_truck_challan_header(
            current_key=header.truck_challan_key,
            truck_no='TK-EDIT-MOD',
            challan_no='CH-NEW',
            no_of_builties=15,
            user=self.user,
        )
        self.assertEqual(updated.truck_challan_key, 'TK-EDIT-MOD-CH-NEW')
        self.assertEqual(updated.no_of_builties, 15)

        # Add 1 builty
        services.create_consignment(
            builty_no='EDIT-B1',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Test Client',
            contact_number='0300-9999999',
            total_amount=Decimal('1000.00'),
            truck_challan_key=updated.truck_challan_key,
            user=self.user,
        )

        # Edit now locked
        with self.assertRaises(ValidationError) as ctx:
            services.update_truck_challan_header(
                current_key=updated.truck_challan_key,
                truck_no='TK-LOCKED',
                challan_no='CH-LOCKED',
                no_of_builties=25,
                user=self.user,
            )
        self.assertIn("Header is locked", str(ctx.exception))

    def test_in_transit_goods_and_arrival_status_update(self):
        header, _ = services.get_or_create_truck_challan(
            truck_no='TK-TRANSIT',
            challan_no='CH-TRANSIT',
            no_of_builties=5,
            user=self.user,
        )

        # Create builty as In Transit with different Karachi truck number
        consignment, _ = services.create_consignment(
            builty_no='TR-9901',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Transit Customer',
            contact_number='0300-7777777',
            total_amount=Decimal('8000.00'),
            goods_condition=GoodsCondition.IN_TRANSIT,
            truck_challan_key=header.truck_challan_key,
            truck_no_karachi='TK-KARACHI-DOC-123',
            nags=10,
            user=self.user,
        )
        self.assertEqual(consignment.goods_condition, GoodsCondition.IN_TRANSIT)
        self.assertEqual(consignment.truck_no_karachi, 'TK-KARACHI-DOC-123')
        self.assertEqual(consignment.nags, 10)

        # Physical arrival -> update status to Received OK
        updated_c = services.update_in_transit_status(
            form_no=consignment.form_no,
            new_goods_condition=GoodsCondition.RECEIVED_OK,
            user=self.user,
        )
        self.assertEqual(updated_c.goods_condition, GoodsCondition.RECEIVED_OK)

        # Audit log captured the status update
        log_entry = ChangeLog.objects.filter(
            builty_no='TR-9901',
            action_type='STATUS_UPDATED',
            field_name='goods_condition',
        ).first()
        self.assertIsNotNone(log_entry)
        self.assertEqual(log_entry.old_value, 'In Transit')
        self.assertEqual(log_entry.new_value, 'Received OK')
        self.assertEqual(log_entry.user, self.user)

    def test_update_arrival_view_and_audit_log_view(self):
        header, _ = services.get_or_create_truck_challan(
            truck_no='TK-VIEW',
            challan_no='CH-VIEW',
            no_of_builties=3,
            user=self.user,
        )
        consignment, _ = services.create_consignment(
            builty_no='TR-VIEW-01',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='View Client',
            contact_number='0300-8888888',
            total_amount=Decimal('4500.00'),
            goods_condition=GoodsCondition.IN_TRANSIT,
            truck_challan_key=header.truck_challan_key,
            user=self.user,
        )

        # POST to update arrival status view
        resp = self.client.post(
            reverse('receivables:update_builty_status'),
            {
                'form_no': consignment.form_no,
                'goods_condition': GoodsCondition.DAMAGED,
                'redirect_key': header.truck_challan_key,
            },
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn(f"?key={header.truck_challan_key}", resp.url)
        consignment.refresh_from_db()
        self.assertEqual(consignment.goods_condition, GoodsCondition.DAMAGED)

        # Verify audit log page renders the transition
        log_resp = self.client.get(reverse('receivables:audit_logs_report'))
        self.assertEqual(log_resp.status_code, 200)
        self.assertContains(log_resp, 'TR-VIEW-01')
        self.assertContains(log_resp, 'In Transit')
        self.assertContains(log_resp, 'Damaged')


class Forms234ConsistencyAndFlowTests(TestCase):
    """
    Tests Form 2 (Delivery & Payment), Form 3 (Agent Recovery), and Form 4 (Loss & Damage Settlement)
    direct access, sidebar navigation, HTMX lookups, POST workflows, and audit logging.
    """

    def setUp(self):
        self.customer = CustomerMaster.objects.create(
            customer_name='Multan Textile Mills',
            contact_number='0300-9991111',
            address='Industrial Estate',
            area_region='Industrial Estate',
        )
        self.agent = AgentMaster.objects.create(
            agent_name='Kamran Agent',
            contact_number='0301-2223333',
            area_region='Industrial Estate',
        )
        self.ok_consignment, _ = services.create_consignment(
            builty_no='KHI-F234-OK',
            customer_type=CustomerCategory.REGULAR,
            customer_id=self.customer.customer_id,
            delivery_mode=DeliveryMode.DELIVER_AT_ADDRESS,
            total_amount=Decimal('10000.00'),
            advance_received=Decimal('1000.00'),
            loading_charges=Decimal('500.00'),
            godam_charges=Decimal('250.00'),
            goods_condition=GoodsCondition.RECEIVED_OK,
        )
        self.lost_consignment, _ = services.create_consignment(
            builty_no='KHI-F234-LOST',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Lost Claim Customer',
            contact_number='0302-4445555',
            delivery_mode=DeliveryMode.COLLECT_FROM_OFFICE,
            total_amount=Decimal('8000.00'),
            advance_received=Decimal('2000.00'),
            goods_condition=GoodsCondition.LOST,
        )

    def test_sidebar_links_and_direct_access_without_login(self):
        for url_name in [
            'receivables:form2_delivery',
            'receivables:form3_recovery',
            'receivables:form4_settlement',
            'receivables:audit_logs_report',
            'masters:customer_master',
        ]:
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, reverse('receivables:form2_delivery'))
            self.assertContains(resp, reverse('receivables:form3_recovery'))
            self.assertContains(resp, reverse('receivables:form4_settlement'))

    def test_form2_lookup_and_post_creates_audit_log(self):
        # Case-insensitive HTMX lookup
        lookup = self.client.get(
            reverse('receivables:htmx_form2_lookup'),
            {'form_no': self.ok_consignment.form_no.lower()},
        )
        self.assertEqual(lookup.status_code, 200)
        self.assertContains(lookup, 'KHI-F234-OK')
        self.assertContains(lookup, '9,750.00')

        # POST delivery + partial payment
        resp = self.client.post(
            reverse('receivables:form2_delivery'),
            {
                'form_no': self.ok_consignment.form_no,
                'delivery_status': DeliveryStatus.DELIVERED,
                'amount_collected': '1750.00',
                'payment_mode': PaymentMode.CASH,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '8,000.00')
        self.ok_consignment.refresh_from_db()
        self.assertEqual(self.ok_consignment.receivable_amount, Decimal('8000.00'))
        self.assertEqual(self.ok_consignment.delivery_status, DeliveryStatus.DELIVERED)
        self.assertTrue(
            ChangeLog.objects.filter(
                builty_no='KHI-F234-OK',
                action_type='DELIVERY_PAYMENT',
            ).exists()
        )

    def test_form3_lookup_and_post_closes_builty_and_logs(self):
        # First mark delivered with 1750 collected so 8000 remains
        services.process_delivery_and_payment(
            self.ok_consignment.form_no,
            DeliveryStatus.DELIVERED,
            Decimal('1750.00'),
        )
        lookup = self.client.get(
            reverse('receivables:htmx_form3_lookup'),
            {'form_no': self.ok_consignment.form_no},
        )
        self.assertEqual(lookup.status_code, 200)
        self.assertContains(lookup, 'Kamran Agent')
        self.assertContains(lookup, '8,000.00')

        resp = self.client.post(
            reverse('receivables:form3_recovery'),
            {
                'form_no': self.ok_consignment.form_no,
                'agent_id': str(self.agent.agent_id),
                'amount_collected': '8000.00',
                'payment_mode': PaymentMode.BANK,
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.ok_consignment.refresh_from_db()
        self.assertEqual(self.ok_consignment.receivable_amount, Decimal('0.00'))
        self.assertEqual(self.ok_consignment.status, ConsignmentStatus.CLOSED)
        self.assertTrue(
            ChangeLog.objects.filter(
                builty_no='KHI-F234-OK',
                action_type='AGENT_RECOVERY',
            ).exists()
        )

    def test_form4_lookup_and_post_settles_and_logs(self):
        # OK builty should be rejected in lookup
        bad_lookup = self.client.get(
            reverse('receivables:htmx_form4_lookup'),
            {'form_no': self.ok_consignment.form_no},
        )
        self.assertEqual(bad_lookup.status_code, 200)
        self.assertContains(bad_lookup, 'Not Eligible for Settlement')

        # Lost builty should be accepted
        good_lookup = self.client.get(
            reverse('receivables:htmx_form4_lookup'),
            {'form_no': self.lost_consignment.form_no},
        )
        self.assertEqual(good_lookup.status_code, 200)
        self.assertContains(good_lookup, 'KHI-F234-LOST')

        resp = self.client.post(
            reverse('receivables:form4_settlement'),
            {
                'form_no': self.lost_consignment.form_no,
                'compensation_paid': '3500.00',
                'remarks': 'Approved by Manager',
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '3,500.00')
        self.lost_consignment.refresh_from_db()
        self.assertEqual(self.lost_consignment.status, ConsignmentStatus.CLOSED)
        self.assertTrue(
            ChangeLog.objects.filter(
                builty_no='KHI-F234-LOST',
                action_type='SETTLEMENT_RECORDED',
            ).exists()
        )


class AllScenariosEndToEndTests(TestCase):
    """
    Comprehensive end-to-end verification of all scenarios across BSD, Smart Business Solution,
    and Required Changes PDFs.
    """

    def setUp(self):
        self.customer = CustomerMaster.objects.create(
            customer_name='Al-Madina Fabrics',
            contact_number='0300-1231234',
            address='Hussain Agahi',
            area_region='Hussain Agahi',
            credit_limit=Decimal('50000.00'),
        )
        self.agent = AgentMaster.objects.create(
            agent_name='Sajid Recovery',
            contact_number='0305-5556666',
            area_region='Hussain Agahi',
        )

    def test_descriptive_endpoints_resolve_and_load(self):
        """All descriptive form endpoints return 200."""
        for path in [
            '/',
            '/consignment-receiving/',
            '/delivery-payment/',
            '/agent-recovery/',
            '/loss-damage-settlement/',
            '/customers/',
            '/audit-logs/',
        ]:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200, f"Failed on {path}")

    def test_type_a_full_advance_delivery_closes_immediately(self):
        """BSD 3.1 Type A: Full advance paid at Karachi -> balance 0 -> Form 2 marks Delivered -> Closed."""
        c, _ = services.create_consignment(
            builty_no='KHI-FULL-ADV',
            customer_type=CustomerCategory.REGULAR,
            customer_id=self.customer.customer_id,
            delivery_mode=DeliveryMode.COLLECT_FROM_OFFICE,
            total_amount=Decimal('5000.00'),
            advance_received=Decimal('5000.00'),
            goods_condition=GoodsCondition.RECEIVED_OK,
        )
        self.assertEqual(c.receivable_amount, Decimal('0.00'))
        self.assertEqual(c.status, ConsignmentStatus.OPEN)

        resp = self.client.post('/delivery-payment/', {
            'form_no': c.form_no,
            'delivery_status': DeliveryStatus.DELIVERED,
            'amount_collected': '0',
            'payment_mode': PaymentMode.CASH,
        })
        self.assertEqual(resp.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.delivery_status, DeliveryStatus.DELIVERED)
        self.assertEqual(c.receivable_amount, Decimal('0.00'))
        self.assertEqual(c.status, ConsignmentStatus.CLOSED)
        self.assertEqual(c.receipts.count(), 0)

    def test_form2_default_select_option_and_multiple_counter_payments(self):
        """Form 2 defaults to '-- Select Option --' and supports repeat payments until balance reaches 0."""
        c, _ = services.create_consignment(
            builty_no='KHI-MULTI-PAY',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Walkin Buyer',
            contact_number='0312-0001111',
            delivery_mode=DeliveryMode.COLLECT_FROM_OFFICE,
            total_amount=Decimal('6000.00'),
            advance_received=Decimal('0.00'),
            goods_condition=GoodsCondition.RECEIVED_OK,
        )

        # Verify default '-- Select Option --' in Form 2 lookup
        lookup = self.client.get('/delivery-payment/lookup/', {'form_no': c.form_no})
        self.assertEqual(lookup.status_code, 200)
        self.assertContains(lookup, 'Select Option')

        # 1st visit: Delivered on credit (0 collected)
        self.client.post('/delivery-payment/', {
            'form_no': c.form_no,
            'delivery_status': DeliveryStatus.DELIVERED,
            'amount_collected': '0',
            'payment_mode': PaymentMode.CASH,
        })
        c.refresh_from_db()
        self.assertEqual(c.delivery_status, DeliveryStatus.DELIVERED)
        self.assertEqual(c.status, ConsignmentStatus.OPEN)
        self.assertEqual(c.receivable_amount, Decimal('6000.00'))

        # 2nd visit: Partial counter payment (2,500 Cash)
        self.client.post('/delivery-payment/', {
            'form_no': c.form_no,
            'delivery_status': DeliveryStatus.DELIVERED,
            'amount_collected': '2500.00',
            'payment_mode': PaymentMode.CASH,
        })
        c.refresh_from_db()
        self.assertEqual(c.receivable_amount, Decimal('3500.00'))
        self.assertEqual(c.status, ConsignmentStatus.OPEN)

        # 3rd visit: Final counter payment (3,500 Bank) -> Closes builty
        self.client.post('/delivery-payment/', {
            'form_no': c.form_no,
            'delivery_status': DeliveryStatus.DELIVERED,
            'amount_collected': '3500.00',
            'payment_mode': PaymentMode.BANK,
        })
        c.refresh_from_db()
        self.assertEqual(c.receivable_amount, Decimal('0.00'))
        self.assertEqual(c.status, ConsignmentStatus.CLOSED)
        self.assertEqual(c.receipts.count(), 2)

    def test_form3_validation_edges_and_htmx_closing_calc(self):
        """Form 3 rejects 0, negative, over-balance, and missing agent; HTMX closing calc works."""
        c, _ = services.create_consignment(
            builty_no='KHI-F3-EDGE',
            customer_type=CustomerCategory.REGULAR,
            customer_id=self.customer.customer_id,
            delivery_mode=DeliveryMode.DELIVER_AT_ADDRESS,
            total_amount=Decimal('4000.00'),
            advance_received=Decimal('1000.00'),
            goods_condition=GoodsCondition.RECEIVED_OK,
        )

        # Missing agent
        r1 = self.client.post('/agent-recovery/', {
            'form_no': c.form_no,
            'agent_id': '',
            'amount_collected': '500',
            'payment_mode': PaymentMode.CASH,
        })
        self.assertContains(r1, 'select a collection agent')

        # Zero amount
        r2 = self.client.post('/agent-recovery/', {
            'form_no': c.form_no,
            'agent_id': str(self.agent.agent_id),
            'amount_collected': '0',
            'payment_mode': PaymentMode.CASH,
        })
        self.assertContains(r2, 'greater than zero')

        # Over-balance amount (opening is 3,000)
        r3 = self.client.post('/agent-recovery/', {
            'form_no': c.form_no,
            'agent_id': str(self.agent.agent_id),
            'amount_collected': '3500',
            'payment_mode': PaymentMode.CASH,
        })
        self.assertContains(r3, 'cannot exceed')

        # HTMX closing balance preview (valid & over-collection)
        calc_ok = self.client.get('/agent-recovery/calc-closing/', {
            'opening_balance': '3000',
            'amount_collected': '1200',
        })
        self.assertContains(calc_ok, '1,800.00')

        calc_err = self.client.get('/delivery-payment/calc-closing/', {
            'opening_balance': '3000',
            'amount_collected': '4000',
        })
        self.assertContains(calc_err, 'cannot exceed')

    def test_form4_in_transit_rejected_and_damaged_settled_once(self):
        """Form 4 rejects In Transit builties, settles Damaged builties, and blocks a second settlement."""
        in_transit, _ = services.create_consignment(
            builty_no='KHI-F4-TRANSIT',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Transit Client',
            contact_number='0300-7770000',
            delivery_mode=DeliveryMode.COLLECT_FROM_OFFICE,
            total_amount=Decimal('3000.00'),
            advance_received=Decimal('0.00'),
            goods_condition=GoodsCondition.IN_TRANSIT,
        )
        lookup_transit = self.client.get('/loss-damage-settlement/lookup/', {'form_no': in_transit.form_no})
        self.assertContains(lookup_transit, 'Not Eligible for Settlement')

        # Transition In Transit -> Damaged via Section 8 flow, then settle in Form 4
        services.update_in_transit_status(in_transit.form_no, GoodsCondition.DAMAGED)
        lookup_damaged = self.client.get('/loss-damage-settlement/lookup/', {'form_no': in_transit.form_no})
        self.assertContains(lookup_damaged, 'KHI-F4-TRANSIT')

        # Negative compensation refused
        r_neg = self.client.post('/loss-damage-settlement/', {
            'form_no': in_transit.form_no,
            'compensation_paid': '-100',
            'remarks': 'Invalid negative',
        })
        self.assertContains(r_neg, 'cannot be negative')

        # Valid settlement succeeds
        r_ok = self.client.post('/loss-damage-settlement/', {
            'form_no': in_transit.form_no,
            'compensation_paid': '1200.00',
            'remarks': 'Damaged box approved by manager',
        })
        self.assertEqual(r_ok.status_code, 200)
        self.assertContains(r_ok, '1,200.00')

        # Second settlement attempt refused via UI
        r_dup = self.client.post('/loss-damage-settlement/', {
            'form_no': in_transit.form_no,
            'compensation_paid': '500.00',
            'remarks': 'Duplicate attempt',
        })
        self.assertContains(r_dup, 'already been saved')

    def test_search_grids_filter_correctly_on_forms_2_3_4(self):
        """Bottom search grids filter by query and dropdowns on Forms 2, 3, and 4."""
        services.create_consignment(
            builty_no='KHI-GRID-OK',
            customer_type=CustomerCategory.REGULAR,
            customer_id=self.customer.customer_id,
            delivery_mode=DeliveryMode.DELIVER_AT_ADDRESS,
            total_amount=Decimal('5000.00'),
            advance_received=Decimal('500.00'),
            goods_condition=GoodsCondition.RECEIVED_OK,
        )
        services.create_consignment(
            builty_no='KHI-GRID-DMG',
            customer_type=CustomerCategory.WALK_IN,
            customer_name='Damaged Grid Party',
            contact_number='0311-9990000',
            delivery_mode=DeliveryMode.COLLECT_FROM_OFFICE,
            total_amount=Decimal('4000.00'),
            advance_received=Decimal('0.00'),
            goods_condition=GoodsCondition.DAMAGED,
        )

        # Form 2 search
        r2 = self.client.get('/delivery-payment/', {'q': 'KHI-GRID-OK', 'delivery_status': 'Not Delivered'})
        self.assertContains(r2, 'KHI-GRID-OK')
        self.assertNotContains(r2, 'KHI-GRID-DMG')

        # Form 3 search by area
        r3 = self.client.get('/agent-recovery/', {'q': 'Hussain Agahi'})
        self.assertContains(r3, 'KHI-GRID-OK')

        # Form 4 filter by condition=Damaged & settlement_status=Pending
        r4 = self.client.get('/loss-damage-settlement/', {'condition': 'Damaged', 'settlement_status': 'Pending'})
        self.assertContains(r4, 'KHI-GRID-DMG')
        self.assertNotContains(r4, 'KHI-GRID-OK')




