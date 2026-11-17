from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from masters.models import CustomerMaster, CustomerStatus, BillingCycle


class CustomerMasterViewTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_customer_list_view_accessible_without_login(self):
        """Customer Master screen is directly accessible without requiring login."""
        response = self.client.get(reverse('masters:customer_master'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Customer Master")

    def test_customer_create_without_login(self):
        """Customers can be created directly from the Customer Master UI without login."""
        data = {
            'customer_name': 'Haseeb & Brothers Traders',
            'contact_number': '0300-4455667',
            'alternate_contact': '061-1234567',
            'address': 'Chowk Shaheedan, Multan',
            'delivery_address': 'Chowk Shaheedan, Multan',
            'area_region': 'Chowk Shaheedan',
            'status': CustomerStatus.ACTIVE,
            'billing_cycle': BillingCycle.WEEKLY,
            'credit_limit': '65000.00',
        }
        response = self.client.post(reverse('masters:customer_master'), data=data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(CustomerMaster.objects.filter(customer_name='Haseeb & Brothers Traders').exists())

    def test_customer_edit_view(self):
        """Can edit a customer directly."""
        cust = CustomerMaster.objects.create(
            customer_name='Original Name Traders',
            contact_number='0301-1111111',
            status=CustomerStatus.ACTIVE,
        )
        response = self.client.post(
            reverse('masters:customer_edit', args=[cust.customer_id]),
            data={
                'customer_name': 'Updated Name Traders',
                'contact_number': '0301-2222222',
                'status': CustomerStatus.ACTIVE,
                'billing_cycle': BillingCycle.DAILY,
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)
        cust.refresh_from_db()
        self.assertEqual(cust.customer_name, 'Updated Name Traders')
        self.assertEqual(cust.contact_number, '0301-2222222')
