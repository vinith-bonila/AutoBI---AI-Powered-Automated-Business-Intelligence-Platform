"""Generate realistic sample datasets for testing AutoBI.

The datasets are deliberately *messy* — currency symbols, percent strings,
mixed date formats, duplicate rows, missing values, inconsistent casing — so
the profiling and cleaning stages have real work to do.

Run:  python data/generate_samples.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent / "samples"
OUT.mkdir(parents=True, exist_ok=True)
random.seed(20240826)


def write(name: str, header: list[str], rows: list[list]) -> None:
    path = OUT / name
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"  {name:34s} {len(rows):>7,} rows x {len(header)} cols")


def money(value: float, symbol: str = "$") -> str:
    return f"{symbol}{value:,.2f}"


# ---------------------------------------------------------------------------
# 1. E-commerce sales
# ---------------------------------------------------------------------------
def ecommerce() -> None:
    categories = {
        "Electronics": (120, 1800, 0.22),
        "Home & Kitchen": (25, 400, 0.35),
        "Apparel": (15, 220, 0.45),
        "Sports & Outdoors": (30, 600, 0.30),
        "Beauty": (8, 150, 0.55),
        "Books": (7, 60, 0.28),
    }
    products = {
        "Electronics": ["Wireless Earbuds", "4K Monitor", "Mechanical Keyboard", "Smart Watch", "USB-C Hub"],
        "Home & Kitchen": ["Espresso Machine", "Air Fryer", "Cookware Set", "Robot Vacuum"],
        "Apparel": ["Running Jacket", "Merino Sweater", "Denim Jeans", "Trail Shoes"],
        "Sports & Outdoors": ["Yoga Mat", "Camping Tent", "Mountain Bike Helmet", "Dumbbell Set"],
        "Beauty": ["Vitamin C Serum", "Hair Dryer", "Gift Set", "Sunscreen SPF50"],
        "Books": ["Data Science Handbook", "Historical Fiction", "Cookbook", "Kids Picture Book"],
    }
    regions = ["North", "South", "East", "West", "Central"]
    region_weights = [0.22, 0.28, 0.18, 0.24, 0.08]
    channels = ["Web", "Mobile App", "Marketplace", "Retail Partner"]
    segments = ["Consumer", "Small Business", "Enterprise"]
    payments = ["Credit Card", "PayPal", "Bank Transfer", "Gift Card"]

    start = date(2023, 1, 1)
    rows: list[list] = []
    order_no = 100000

    for day_offset in range(730):
        current = start + timedelta(days=day_offset)
        # Seasonality: Q4 lift, weekend lift, plus a growth trend.
        seasonal = 1.0 + 0.45 * (current.month in (11, 12)) + 0.12 * (current.weekday() >= 5)
        trend = 1.0 + (day_offset / 730) * 0.35
        base_orders = int(random.gauss(20 * seasonal * trend, 4))
        # South region surge in the final quarter — a real signal to detect.
        for _ in range(max(3, base_orders)):
            order_no += 1
            category = random.choice(list(categories))
            lo, hi, margin_base = categories[category]
            unit_price = round(random.uniform(lo, hi), 2)
            qty = random.choices([1, 2, 3, 4, 5], weights=[55, 22, 12, 7, 4])[0]
            weights = list(region_weights)
            if day_offset > 550:
                weights[1] += 0.18  # South surge
            region = random.choices(regions, weights=weights)[0]
            gross = unit_price * qty
            discount_pct = random.choices([0, 5, 10, 15, 25], weights=[52, 20, 15, 9, 4])[0]
            revenue = gross * (1 - discount_pct / 100)
            # Margin compresses over time (rising costs) — another real signal.
            margin = margin_base - (day_offset / 730) * 0.08 + random.uniform(-0.05, 0.05)
            cost = revenue * (1 - max(0.05, margin))
            profit = revenue - cost

            # Mixed date formats across the file.
            if day_offset % 7 == 3:
                date_str = current.strftime("%m/%d/%Y")
            else:
                date_str = current.isoformat()

            rows.append([
                f"ORD-{order_no}",
                date_str,
                f"CUST-{random.randint(1000, 9500)}",
                random.choice(products[category]),
                category,
                region,
                random.choice(channels),
                random.choice(segments),
                random.choice(payments),
                qty,
                money(unit_price),
                f"{discount_pct}%",
                money(revenue),
                money(round(cost, 2)),
                money(round(profit, 2)),
                random.choice([3, 4, 4, 5, 5, 5, 2, 1, ""]),
                random.choice(["Yes", "No", "No", "No", "No"]),
            ])

    # Inject messiness: duplicates and missing values.
    for _ in range(1243):
        rows.append(list(random.choice(rows)))
    for _ in range(900):
        row = random.choice(rows)
        row[7] = ""  # missing customer segment
    for _ in range(160):
        row = random.choice(rows)
        row[12] = ""  # missing revenue
    for _ in range(300):
        row = random.choice(rows)
        row[5] = random.choice([" north ", "SOUTH", "east", "West "])  # casing noise

    random.shuffle(rows)
    write(
        "ecommerce_sales.csv",
        [
            "order_id", "order_date", "customer_id", "product_name", "category",
            "region", "sales_channel", "customer_segment", "payment_method",
            "quantity", "unit_price", "discount_pct", "revenue", "cost",
            "profit", "satisfaction_rating", "returned",
        ],
        rows,
    )


# ---------------------------------------------------------------------------
# 2. HR employee data
# ---------------------------------------------------------------------------
def hr() -> None:
    departments = {
        "Engineering": (95000, 190000, 0.11),
        "Sales": (60000, 165000, 0.24),
        "Marketing": (58000, 130000, 0.18),
        "Customer Support": (42000, 78000, 0.31),
        "Finance": (70000, 155000, 0.09),
        "Human Resources": (55000, 120000, 0.14),
        "Operations": (50000, 115000, 0.19),
    }
    titles = {
        "Engineering": ["Software Engineer", "Senior Engineer", "Staff Engineer", "Engineering Manager", "QA Engineer"],
        "Sales": ["Account Executive", "Sales Development Rep", "Sales Manager", "Solutions Consultant"],
        "Marketing": ["Marketing Specialist", "Content Manager", "Growth Marketer", "Brand Manager"],
        "Customer Support": ["Support Agent", "Support Lead", "Technical Support Engineer"],
        "Finance": ["Financial Analyst", "Controller", "Accountant", "FP&A Manager"],
        "Human Resources": ["Recruiter", "HR Business Partner", "People Ops Manager"],
        "Operations": ["Operations Analyst", "Logistics Coordinator", "Program Manager"],
    }
    locations = ["Austin", "Berlin", "London", "Singapore", "Toronto", "Remote"]
    education = ["High School", "Bachelor's", "Master's", "PhD"]
    genders = ["Female", "Male", "Non-binary", "Prefer not to say"]

    rows: list[list] = []
    for i in range(1, 2401):
        dept = random.choices(
            list(departments), weights=[28, 20, 12, 16, 8, 6, 10]
        )[0]
        lo, hi, attrition = departments[dept]
        level = random.choices([1, 2, 3, 4], weights=[40, 32, 20, 8])[0]
        salary = lo + (hi - lo) * (level / 4) * random.uniform(0.75, 1.15)
        hire = date(2015, 1, 1) + timedelta(days=random.randint(0, 3400))
        tenure_years = round((date(2025, 6, 30) - hire).days / 365.25, 1)
        left = random.random() < attrition
        term = (
            (hire + timedelta(days=random.randint(120, max(150, (date(2025, 6, 30) - hire).days))))
            if left
            else None
        )
        perf = random.choices([1, 2, 3, 4, 5], weights=[3, 9, 42, 33, 13])[0]
        rows.append([
            f"EMP{i:05d}",
            random.choice(titles[dept]),
            dept,
            random.choice(locations),
            random.choice(genders),
            random.randint(22, 63),
            random.choice(education),
            hire.strftime("%d/%m/%Y"),
            term.strftime("%d/%m/%Y") if term else "",
            "Yes" if left else "No",
            f"{salary:,.0f}",
            round(random.uniform(0, 0.25) * salary, 0) if random.random() > 0.35 else "",
            level,
            perf,
            tenure_years,
            random.randint(0, 28),
            round(random.uniform(45, 99), 1),
        ])

    for _ in range(80):
        row = random.choice(rows)
        row[6] = ""  # missing education
    for _ in range(40):
        row = random.choice(rows)
        row[5] = ""  # missing age
    for _ in range(35):
        rows.append(list(random.choice(rows)))

    random.shuffle(rows)
    write(
        "hr_employees.csv",
        [
            "employee_id", "job_title", "department", "location", "gender", "age",
            "education_level", "hire_date", "termination_date", "left_company",
            "annual_salary", "bonus_amount", "job_level", "performance_rating",
            "tenure_years", "training_hours", "engagement_score",
        ],
        rows,
    )


# ---------------------------------------------------------------------------
# 3. Marketing campaign data
# ---------------------------------------------------------------------------
def marketing() -> None:
    channels = {
        "Paid Search": (0.041, 0.062, 2.10),
        "Paid Social": (0.018, 0.031, 1.15),
        "Display": (0.006, 0.011, 0.62),
        "Email": (0.092, 0.180, 0.08),
        "Affiliate": (0.028, 0.049, 1.40),
        "Video": (0.011, 0.022, 0.95),
    }
    objectives = ["Awareness", "Consideration", "Conversion", "Retention"]
    audiences = ["New Visitors", "Retargeting", "Lookalike", "Existing Customers"]
    devices = ["Desktop", "Mobile", "Tablet"]
    regions = ["North America", "EMEA", "APAC", "LATAM"]

    rows: list[list] = []
    start = date(2024, 1, 1)
    campaign_no = 0
    for week in range(78):
        week_start = start + timedelta(weeks=week)
        for channel, (ctr_lo, ctr_hi, cpc) in channels.items():
            for _ in range(random.randint(2, 5)):
                campaign_no += 1
                impressions = random.randint(20_000, 900_000)
                ctr = random.uniform(ctr_lo, ctr_hi)
                clicks = int(impressions * ctr)
                effective_cpc = cpc * random.uniform(0.7, 1.4)
                spend = clicks * effective_cpc
                cvr = random.uniform(0.012, 0.075)
                # Email converts far better — a segment insight worth surfacing.
                if channel == "Email":
                    cvr *= 2.2
                conversions = max(0, int(clicks * cvr))
                revenue = conversions * random.uniform(45, 320)
                rows.append([
                    f"CMP-{campaign_no:05d}",
                    f"{channel} {week_start.strftime('%b %Y')} W{week % 52 + 1}",
                    channel,
                    random.choice(objectives),
                    random.choice(audiences),
                    random.choice(devices),
                    random.choice(regions),
                    week_start.isoformat(),
                    (week_start + timedelta(days=6)).isoformat(),
                    impressions,
                    clicks,
                    f"{ctr * 100:.2f}%",
                    money(round(spend, 2)),
                    conversions,
                    f"{(conversions / clicks * 100) if clicks else 0:.2f}%",
                    money(round(revenue, 2)),
                    round(revenue / spend, 2) if spend else 0,
                ])

    for _ in range(120):
        row = random.choice(rows)
        row[5] = ""  # missing device
    for _ in range(60):
        rows.append(list(random.choice(rows)))

    random.shuffle(rows)
    write(
        "marketing_campaigns.csv",
        [
            "campaign_id", "campaign_name", "channel", "objective", "audience",
            "device", "region", "start_date", "end_date", "impressions",
            "clicks", "ctr", "spend", "conversions", "conversion_rate",
            "revenue", "roas",
        ],
        rows,
    )


# ---------------------------------------------------------------------------
# 4. Financial transactions
# ---------------------------------------------------------------------------
def finance() -> None:
    categories = {
        "Payroll": (-45000, -8000),
        "Software & SaaS": (-9000, -200),
        "Office & Facilities": (-12000, -150),
        "Travel": (-6000, -80),
        "Marketing": (-30000, -500),
        "Professional Services": (-25000, -800),
        "Client Payment": (5000, 180000),
        "Interest Income": (50, 4200),
        "Refund": (-4000, -60),
        "Equipment": (-40000, -300),
    }
    accounts = ["Operating - USD", "Operating - EUR", "Payroll Account", "Reserve Account"]
    methods = ["ACH", "Wire", "Card", "Check", "Direct Debit"]
    entities = ["HQ", "EU Subsidiary", "APAC Subsidiary"]
    statuses = ["Cleared", "Cleared", "Cleared", "Pending", "Failed"]

    rows: list[list] = []
    txn = 500000
    start = date(2023, 7, 1)
    for day in range(760):
        current = start + timedelta(days=day)
        if current.weekday() >= 5 and random.random() > 0.25:
            continue
        for _ in range(random.randint(4, 16)):
            txn += 1
            category = random.choices(
                list(categories),
                weights=[6, 14, 8, 9, 11, 7, 24, 4, 8, 9],
            )[0]
            lo, hi = categories[category]
            amount = round(random.uniform(lo, hi), 2)
            rows.append([
                f"TXN{txn}",
                current.strftime("%Y-%m-%d"),
                random.choice(accounts),
                random.choice(entities),
                category,
                "Income" if amount > 0 else "Expense",
                random.choice(methods),
                money(amount) if amount >= 0 else f"({money(abs(amount))})",
                round(abs(amount) * random.uniform(0.0, 0.21), 2),
                random.choice(statuses),
                f"Vendor {random.randint(100, 480)}" if amount < 0 else f"Client {random.randint(1, 90)}",
                random.choice(["Q1", "Q2", "Q3", "Q4"]),
            ])

    for _ in range(400):
        row = random.choice(rows)
        row[10] = ""  # missing counterparty
    for _ in range(210):
        rows.append(list(random.choice(rows)))

    random.shuffle(rows)
    write(
        "financial_transactions.csv",
        [
            "transaction_id", "transaction_date", "account", "entity", "category",
            "transaction_type", "payment_method", "amount", "tax_amount",
            "status", "counterparty", "fiscal_quarter",
        ],
        rows,
    )


# ---------------------------------------------------------------------------
# 5. Edge cases used by the test suite
# ---------------------------------------------------------------------------
def edge_cases() -> None:
    write("edge_tiny.csv", ["name", "score"], [["A", 1], ["B", 2], ["C", 3]])

    write(
        "edge_categorical_only.csv",
        ["country", "status", "tier"],
        [
            [random.choice(["Germany", "France", "Spain", "Italy"]),
             random.choice(["active", "churned", "trial"]),
             random.choice(["Gold", "Silver", "Bronze"])]
            for _ in range(400)
        ],
    )

    write(
        "edge_numeric_only.csv",
        ["sensor_a", "sensor_b", "sensor_c", "sensor_d"],
        [
            [
                round(random.gauss(50, 12), 3),
                round(random.gauss(50, 12) * 1.4 + random.gauss(0, 3), 3),
                round(random.uniform(0, 100), 3),
                round(random.expovariate(0.05), 3),
            ]
            for _ in range(1200)
        ],
    )

    rows = []
    for i in range(300):
        rows.append([
            f"item-{i}",
            random.choice(["", "12", "abc", "3.5", None or ""]),
            "",
            random.choice(["2024-01-05", "not a date", "13/13/2024", ""]),
        ])
    write("edge_messy.csv", ["item", "mixed_values", "always_empty", "bad_dates"], rows)


if __name__ == "__main__":
    print("Generating sample datasets in", OUT)
    ecommerce()
    hr()
    marketing()
    finance()
    edge_cases()
    print("Done.")
