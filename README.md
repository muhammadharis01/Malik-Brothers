# Malik Brothers Transporters - Multan Receivables System

A custom, server-rendered Django web application tailored for the Malik Brothers Transporters Multan office to track arriving consignments (builties) from Karachi, record deliveries, manage counter and field agent cash recoveries, and settle loss/damage claims.

Designed with large inputs, accessible typography (18px+ base font), high-contrast status badges, HTMX-driven reactive lookups, and strict backend business validation.

---

## 1. Tech Stack

- **Backend**: Python 3.13 / 3.12, Django 6.1 / 5.x
- **Database**: PostgreSQL 16 (never SQLite) via `psycopg` (binary) and configuration via `python-decouple`
- **Frontend / Interactivity**: Server-rendered Django templates + HTMX (`django-htmx`)
- **Styling**: Tailwind CSS standalone binary via `django-tailwind-cli` (no Node.js build step required)
- **Admin Portal**: `django-unfold` for Customer Master, Agent Master, and user/group administration
- **Icons & Charts**: Inline Lucide SVGs, Chart.js (via CDN for dashboard KPIs)
- **Architecture**: Domain services in `receivables/services.py`, transactions wrapped with `transaction.atomic`, all monetary values represented strictly with `Decimal`.

---

## 2. Roles & Permissions

View-level permission checks (`@role_required`) enforce group access control across all screens:

| Role | Access & Responsibilities | Demo Username | Demo Password |
|---|---|---|---|
| **Admin** | Full system access: Customer Master, Agent Master, all 4 forms, reports, user management | `admin` | `Malik123!` |
| **Receiving Clerk** | **Form 1: Consignment Receiving** (records arriving builties from Karachi) | `receiving_clerk` | `Malik123!` |
| **Delivery Clerk** | **Form 2: Delivery & Payment** (records goods delivery and counter cash collection) | `delivery_clerk` | `Malik123!` |
| **Accounts Clerk** | **Form 3: Agent Recovery** and all reports (records agent collections, views outstanding) | `accounts_clerk` | `Malik123!` |
| **Manager** | **Form 4: Loss & Damage Settlement** and reports (approves loss/damage compensation, read-only elsewhere) | `manager` | `Malik123!` |

> **Note**: Demo passwords are provided here in the README only and are never hard-coded in code comments.

---

## 3. Installation & Setup

### Prerequisites
- Python 3.12+ (Python 3.13 supported)
- PostgreSQL 16 running locally or accessible via network

### Step 1: Clone and Activate Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
Copy `.env.example` to `.env` and verify database credentials:
```bash
cp .env.example .env
```
Ensure your `.env` contains:
```ini
SECRET_KEY=your-secure-random-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
DB_NAME=mb_receivables
DB_USER=mb_user
DB_PASSWORD=change_me
DB_HOST=localhost
DB_PORT=5432
CREDIT_CHECK_ACTION=WARN
```

### Step 3: Run Database Migrations
```bash
python manage.py migrate
```

### Step 4: Build Tailwind CSS
```bash
python manage.py tailwind build --skip-checks
```

### Step 5: Seed Demonstration Data
Seed 5 role-based demo accounts, 6 regular customers, 4 agents, and 25 consignments in diverse operational states:
```bash
python manage.py seed_demo
```

### Step 6: Run Tests
Execute the automated test suite covering all business rules and the Smart Solution PDF worked example:
```bash
python manage.py test receivables
```

### Step 7: Start Development Server
```bash
python manage.py runserver
```
Visit:
- **Operations Portal**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Unfold Master Admin**: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## 4. Business Rules Enforced

1. **Auto-Generated Reference Number**: Primary key `form_no` format `MB-YYYY-XXXXXX` (e.g. `MB-2026-000001`), generated on Form 1 save, unique, and never reused.
2. **Receivable Calculation**: `Balance Receivable = Total Freight Charges - Advance Received - SUM(Payment Receipts)`. Always recalculated inside DB transaction from persisted records, never trusted from frontend input.
3. **Over-collection Prevention**: Amount collected cannot exceed opening balance.
4. **Conditional Amount Entry in Form 2**: In Form 2, amount collection is enabled **only** when `Delivery Status = Delivered`.
5. **Loss & Damage Gate**: Form 4 strictly accepts builties with `Goods Condition = Lost` or `Damaged`. Only 1 settlement is allowed per builty.
6. **Automatic Builty Closure**: A builty is marked `Closed` when delivered with `receivable = 0`, or upon saving a Form 4 settlement.
7. **Credit Checks**: Evaluates regular customers against `hold_flag` and `credit_limit`. Warns or blocks credit delivery according to the `CREDIT_CHECK_ACTION` setting (`WARN` or `BLOCK`).
8. **Immutability & Reversals**: Records are never hard-deleted from operational tables.

---

## 5. Security & Deployment Check

Running Django's deployment check:
```bash
python manage.py check --deploy
```

- When running locally with `DEBUG=True`, security warnings regarding SSL redirection and HSTS are reported as advisory.
- When `DEBUG=False` is set in `.env` for production, hardened settings automatically activate:
  - `CSRF_COOKIE_SECURE = True`
  - `SESSION_COOKIE_SECURE = True`
  - `SESSION_COOKIE_HTTPONLY = True`
  - `SECURE_CONTENT_TYPE_NOSNIFF = True`
  - `X_FRAME_OPTIONS = 'DENY'`
  - `SECURE_SSL_REDIRECT = True`
  - `SECURE_HSTS_SECONDS = 31536000` (1 year)
  - `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`
  - `SECURE_HSTS_PRELOAD = True`

---

## 6. Worked Example (Smart Solution PDF, Section 6)

The automated tests in `receivables/tests.py` verify the exact scenario:
1. **Form 1**: Consignment with Total 10,000, Advance 1,000, Condition OK &rarr; Reference No. generated, Balance Receivable = **Rs. 9,000**.
2. **Form 2**: Goods marked Delivered, Counter collects 1,500 &rarr; Cumulative Received = **Rs. 2,500**, Closing Balance = **Rs. 7,500**.
3. **Form 3**: Field agent collects 1,000 &rarr; Cumulative Received = **Rs. 3,500**, Closing Balance = **Rs. 6,500**.
4. **Form 3**: Field agent recovers remaining 6,500 &rarr; Closing Balance = **Rs. 0**, Builty status transitions to **Closed**.
5. **Form 1**: Consignment with Total 8,000, Advance 2,000, Condition Lost &rarr; Balance = **Rs. 6,000**, flagged for Form 4.
6. **Form 4**: Manager approves compensation of 3,000 &rarr; Settlement record stored, Builty status transitions to **Closed**.

---

## 7. Open Questions (Out of Scope for Phase 1)

As specified in the project requirements, the following areas are reserved for subsequent phases and should be confirmed with the client:

1. **Commission on Karachi Advance**:
   - The BSD mentions Multan earning a fixed percentage of the advance paid at Karachi.
   - *Question for Client*: What is the commission percentage or formula? Is commission earned on arrival, unloading, or delivery? Should commission be tracked in a separate ledger or credited against Karachi head office accounts?
2. **Agent Cash-Deposit Reconciliation**:
   - The BSD notes the need to check that each agent deposits exactly what they collected.
   - *Question for Client*: Does the Multan cashier require a daily cash-handover shift reconciliation screen (e.g., cash bag count vs. receipts issued by agent)?
3. **Disputes and Reversing Adjustments**:
   - The BSD mentions that disputes over balances are settled through negotiation.
   - *Question for Client*: What is the approved business mechanism for a dispute reduction? Should a negotiated markdown require a credit note / discount voucher table, and who possesses the role authorization to approve write-offs?
4. **Periodic Billing & Statements for Regular Customers**:
   - Regular customers have billing cycles (`Daily`, `Weekly`, `Month-end`).
   - *Question for Client*: Should statements consolidate unpaid builties into a formal monthly invoice PDF with aging buckets (30/60/90 days), and should payments be allowed at statement level or always tied to individual builties?
5. **Karachi Office System Integration**:
   - Multan currently manually keys in Karachi Builty numbers and freight amounts.
   - *Question for Client*: Will Karachi provide an automated EDI, REST API, or daily SFTP/CSV export of booked builties so Multan can import manifests electronically upon truck departure?
6. **SMS Notifications**:
   - *Question for Client*: Which SMS gateway provider (e.g., Telenor, Jazz, Zong, Twilio) will be utilized for automated SMS alerts on builty arrival and delivery payment?

