"""
Holiday Parser Test - EXACT CLONE of holiday_updater.py logic.

This test validates the holiday parsing logic by:
1. Fetching the actual Zerodha holiday page
2. Parsing it using the EXACT same regex patterns from holiday_updater.py
3. Comparing results with official NSE calendar
4. Writing to a test table to validate DB operations

Created: 2026-03-10
Purpose: Investigate parsing bugs causing incorrect holiday entries
"""
import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Tuple

import httpx
import asyncpg


# ============================================================================
# EXACT CLONE FROM holiday_updater.py (lines 27-40)
# ============================================================================
@dataclass
class HolidayEntry:
    """Parsed holiday entry from Zerodha calendar."""
    holiday_date: date
    description: str
    exchange: str = "BOTH"
    is_full_day: bool = True


# ============================================================================
# EXACT CLONE FROM holiday_updater.py (lines 67-79)
# ============================================================================
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}


# ============================================================================
# EXACT CLONE FROM holiday_updater.py (lines 395-445)
# ============================================================================
def _parse_date_string_ORIGINAL(date_str: str, default_year: int) -> Optional[date]:
    """
    EXACT CLONE of holiday_updater.py _parse_date_string method.
    """
    date_str = date_str.strip().lower()
    
    # Try "January 26, 2026" format
    match = re.match(r'(\w+)\s+(\d{1,2}),?\s*(\d{4})?', date_str)
    if match:
        month_name = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else default_year
        
        month = MONTH_MAP.get(month_name.lower())
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass
    
    # Try "26 Jan 2026" format
    match = re.match(r'(\d{1,2})\s+(\w+)\s*(\d{4})?', date_str)
    if match:
        day = int(match.group(1))
        month_name = match.group(2)
        year = int(match.group(3)) if match.group(3) else default_year
        
        month = MONTH_MAP.get(month_name.lower())
        if month:
            try:
                return date(year, month, day)
            except ValueError:
                pass
    
    # Try ISO format "2026-01-26"
    match = re.match(r'(\d{4})-(\d{2})-(\d{2})', date_str)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    
    return None


# ============================================================================
# EXACT CLONE FROM holiday_updater.py (lines 347-393)
# ============================================================================
def _parse_holiday_html_ORIGINAL(html: str, year: int) -> List[HolidayEntry]:
    """
    EXACT CLONE of holiday_updater.py _parse_holiday_html method.
    
    This is the BUGGY version that we're testing.
    """
    holidays = []
    
    # Pattern to match date formats like "January 26, 2026" or "26 Jan 2026"
    # Also handles table row patterns
    date_patterns = [
        # "January 26, 2026" format
        r'(\w+)\s+(\d{1,2}),?\s*(\d{4})',
        # "26 Jan 2026" format
        r'(\d{1,2})\s+(\w+)\s+(\d{4})',
        # "2026-01-26" ISO format
        r'(\d{4})-(\d{2})-(\d{2})',
    ]
    
    # Try to find table rows with holiday data
    # Pattern for table rows: <tr>...<td>date</td><td>name</td>...</tr>
    row_pattern = r'<tr[^>]*>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>([^<]+)</td>.*?</tr>'
    
    rows = re.findall(row_pattern, html, re.DOTALL | re.IGNORECASE)
    
    print(f"\n[ORIGINAL PARSER] Found {len(rows)} table rows")
    print(f"[ORIGINAL PARSER] First 5 rows raw data:")
    for i, row in enumerate(rows[:5]):
        print(f"  Row {i}: date_str='{row[0].strip()}', name='{row[1].strip()}'")
    
    for row_data in rows:
        if len(row_data) >= 2:
            date_str = row_data[0].strip()
            name = row_data[1].strip()
            
            parsed_date = _parse_date_string_ORIGINAL(date_str, year)
            if parsed_date and parsed_date.year == year:
                # Clean up the holiday name
                name = re.sub(r'<[^>]+>', '', name)  # Remove any HTML tags
                name = name.strip()
                
                if name and len(name) > 2:
                    holidays.append(HolidayEntry(
                        holiday_date=parsed_date,
                        description=name,
                        exchange="BOTH",
                        is_full_day=True,
                    ))
    
    # Deduplicate by date
    seen_dates = set()
    unique_holidays = []
    for h in holidays:
        if h.holiday_date not in seen_dates:
            seen_dates.add(h.holiday_date)
            unique_holidays.append(h)
    
    return sorted(unique_holidays, key=lambda h: h.holiday_date)


# ============================================================================
# FIXED PARSER - Correct implementation
# ============================================================================
def _parse_holiday_html_FIXED(html: str, year: int) -> List[HolidayEntry]:
    """
    FIXED version that correctly parses the 4-column table:
    Date | Day | Holiday | Exchanges
    
    The bug in the original: it captures only 2 <td> elements,
    getting Date and Day instead of Date and Holiday.
    """
    holidays = []
    
    # The actual HTML structure has 4 columns:
    # <tr><td>Date</td><td>Day</td><td>Holiday</td><td>Exchanges</td></tr>
    # We need to capture the 1st (date) and 3rd (holiday name) columns
    
    # Pattern to capture all 4 td elements
    row_pattern = r'<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>'
    
    rows = re.findall(row_pattern, html, re.DOTALL | re.IGNORECASE)
    
    print(f"\n[FIXED PARSER] Found {len(rows)} table rows")
    print(f"[FIXED PARSER] First 5 rows raw data:")
    for i, row in enumerate(rows[:5]):
        date_str = re.sub(r'<[^>]+>', '', row[0]).strip()
        day_str = re.sub(r'<[^>]+>', '', row[1]).strip()
        holiday_str = re.sub(r'<[^>]+>', '', row[2]).strip()
        print(f"  Row {i}: date='{date_str}', day='{day_str}', holiday='{holiday_str}'")
    
    for row_data in rows:
        if len(row_data) >= 3:
            # Column 0 = Date, Column 1 = Day, Column 2 = Holiday name
            date_str = re.sub(r'<[^>]+>', '', row_data[0]).strip()
            holiday_name = re.sub(r'<[^>]+>', '', row_data[2]).strip()
            
            parsed_date = _parse_date_string_ORIGINAL(date_str, year)
            if parsed_date and parsed_date.year == year:
                if holiday_name and len(holiday_name) > 2:
                    holidays.append(HolidayEntry(
                        holiday_date=parsed_date,
                        description=holiday_name,
                        exchange="BOTH",
                        is_full_day=True,
                    ))
    
    # Deduplicate by date
    seen_dates = set()
    unique_holidays = []
    for h in holidays:
        if h.holiday_date not in seen_dates:
            seen_dates.add(h.holiday_date)
            unique_holidays.append(h)
    
    return sorted(unique_holidays, key=lambda h: h.holiday_date)


async def fetch_zerodha_page() -> str:
    """Fetch the actual Zerodha holiday calendar page."""
    url = "https://zerodha.com/marketintel/holiday-calendar/"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; IcebergBot/1.0)",
                "Accept": "text/html,application/xhtml+xml",
            },
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text


async def write_to_test_table(holidays: List[HolidayEntry], table_suffix: str = "") -> Tuple[int, int]:
    """Write holidays to test table."""
    table_name = f"app.market_holidays_test{table_suffix}"
    
    conn = await asyncpg.connect(
        host="34.180.57.7",
        port=5432,
        user="iceberg",
        password="xw8vntEkMkLnOrwA6qsULpGmB1wUmgpT",
        database="iceberg",
    )
    
    try:
        # Clear existing data
        await conn.execute(f"TRUNCATE {table_name}")
        
        inserted = 0
        for h in holidays:
            await conn.execute(
                f"""
                INSERT INTO {table_name} (holiday_date, exchange, description, is_full_day)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (holiday_date) DO UPDATE SET
                    exchange = EXCLUDED.exchange,
                    description = EXCLUDED.description,
                    is_full_day = EXCLUDED.is_full_day,
                    updated_at = NOW()
                """,
                h.holiday_date,
                h.exchange,
                h.description,
                h.is_full_day,
            )
            inserted += 1
        
        return (inserted, 0)
    finally:
        await conn.close()


async def compare_with_production() -> None:
    """Compare test results with production table."""
    conn = await asyncpg.connect(
        host="34.180.57.7",
        port=5432,
        user="iceberg",
        password="xw8vntEkMkLnOrwA6qsULpGmB1wUmgpT",
        database="iceberg",
    )
    
    try:
        print("\n" + "="*80)
        print("COMPARISON: Production vs Test Table")
        print("="*80)
        
        # Get production data
        prod_rows = await conn.fetch("""
            SELECT holiday_date, description 
            FROM app.market_holidays 
            WHERE EXTRACT(YEAR FROM holiday_date) = 2026
            ORDER BY holiday_date
        """)
        
        # Get test data
        test_rows = await conn.fetch("""
            SELECT holiday_date, description 
            FROM app.market_holidays_test 
            WHERE EXTRACT(YEAR FROM holiday_date) = 2026
            ORDER BY holiday_date
        """)
        
        print(f"\nProduction table: {len(prod_rows)} entries")
        print(f"Test table (fixed): {len(test_rows)} entries")
        
        # Create lookup dicts
        prod_dict = {row['holiday_date']: row['description'] for row in prod_rows}
        test_dict = {row['holiday_date']: row['description'] for row in test_rows}
        
        # Find differences
        print("\n--- DIFFERENCES ---")
        
        all_dates = set(prod_dict.keys()) | set(test_dict.keys())
        differences = []
        
        for d in sorted(all_dates):
            prod_desc = prod_dict.get(d, "NOT IN PROD")
            test_desc = test_dict.get(d, "NOT IN TEST")
            
            if prod_desc != test_desc:
                differences.append((d, prod_desc, test_desc))
                print(f"  {d}: PROD='{prod_desc}' vs TEST='{test_desc}'")
        
        if not differences:
            print("  No differences found!")
        else:
            print(f"\n  Total differences: {len(differences)}")
        
    finally:
        await conn.close()


# ============================================================================
# OFFICIAL NSE HOLIDAYS 2026 (from NSE website)
# ============================================================================
OFFICIAL_NSE_HOLIDAYS_2026 = [
    (date(2026, 1, 26), "Republic Day"),
    (date(2026, 3, 3), "Holi"),
    (date(2026, 3, 26), "Ram Navami"),  # Shri Ram Navami
    (date(2026, 3, 31), "Mahavir Jayanti"),  # Shri Mahavir Jayanti
    (date(2026, 4, 3), "Good Friday"),
    (date(2026, 4, 14), "Dr. Ambedkar Jayanti"),
    (date(2026, 5, 1), "Maharashtra Day"),
    (date(2026, 5, 28), "Bakri Eid"),  # Eid ul-Adha
    (date(2026, 6, 26), "Muharram"),  # Moharram
    (date(2026, 9, 14), "Ganesh Chaturthi"),
    (date(2026, 10, 2), "Mahatma Gandhi Jayanti"),
    (date(2026, 10, 20), "Dussehra"),
    (date(2026, 11, 10), "Diwali Balipratipada"),
    (date(2026, 11, 24), "Guru Nanak Jayanti"),
    (date(2026, 12, 25), "Christmas"),
]


async def main():
    print("="*80)
    print("HOLIDAY PARSER VALIDATION TEST")
    print("="*80)
    print(f"Test Date: {datetime.now().isoformat()}")
    print(f"Purpose: Validate holiday parsing logic from holiday_updater.py")
    
    # Step 1: Fetch actual Zerodha page
    print("\n[STEP 1] Fetching Zerodha holiday calendar page...")
    html = await fetch_zerodha_page()
    print(f"  Fetched {len(html)} bytes")
    
    # Step 2: Parse with ORIGINAL (buggy) logic
    print("\n[STEP 2] Parsing with ORIGINAL logic (from holiday_updater.py)...")
    original_holidays = _parse_holiday_html_ORIGINAL(html, 2026)
    print(f"\n  ORIGINAL parser found {len(original_holidays)} holidays:")
    for h in original_holidays:
        print(f"    {h.holiday_date}: {h.description}")
    
    # Step 3: Parse with FIXED logic
    print("\n[STEP 3] Parsing with FIXED logic...")
    fixed_holidays = _parse_holiday_html_FIXED(html, 2026)
    print(f"\n  FIXED parser found {len(fixed_holidays)} holidays:")
    for h in fixed_holidays:
        print(f"    {h.holiday_date}: {h.description}")
    
    # Step 4: Compare with official NSE calendar
    print("\n[STEP 4] Comparing with OFFICIAL NSE holidays...")
    print(f"  Official NSE 2026 holidays: {len(OFFICIAL_NSE_HOLIDAYS_2026)}")
    
    fixed_dates = {h.holiday_date for h in fixed_holidays}
    official_dates = {d for d, _ in OFFICIAL_NSE_HOLIDAYS_2026}
    
    missing_from_zerodha = official_dates - fixed_dates
    extra_in_zerodha = fixed_dates - official_dates
    
    if missing_from_zerodha:
        print(f"\n  MISSING from Zerodha (in official NSE):")
        for d in sorted(missing_from_zerodha):
            name = next((n for dt, n in OFFICIAL_NSE_HOLIDAYS_2026 if dt == d), "?")
            print(f"    {d}: {name}")
    
    if extra_in_zerodha:
        print(f"\n  EXTRA in Zerodha (not in official NSE):")
        for d in sorted(extra_in_zerodha):
            name = next((h.description for h in fixed_holidays if h.holiday_date == d), "?")
            print(f"    {d}: {name}")
    
    # Step 5: Write fixed results to test table
    print("\n[STEP 5] Writing FIXED results to test table...")
    inserted, _ = await write_to_test_table(fixed_holidays)
    print(f"  Inserted {inserted} rows into app.market_holidays_test")
    
    # Step 6: Compare with production
    await compare_with_production()
    
    # Step 7: Identify the BUG
    print("\n" + "="*80)
    print("BUG ANALYSIS")
    print("="*80)
    print("""
THE BUG in holiday_updater.py _parse_holiday_html (lines 347-393):

The regex pattern captures only the FIRST TWO <td> elements:
    row_pattern = r'<tr[^>]*>.*?<td[^>]*>([^<]+)</td>.*?<td[^>]*>([^<]+)</td>.*?</tr>'

But the Zerodha table has FOUR columns:
    | Date | Day | Holiday | Exchanges |

So the parser captures:
    - Column 0 (Date) -> Correctly parsed as date
    - Column 1 (Day)  -> INCORRECTLY used as holiday name!

This is why we see entries like:
    - "Thursday" instead of "Municipal Corporation Elections"
    - "Tuesday" instead of "Holi"
    - "Tuesday" instead of "Mahavir Jayanti"

The fix is to capture all 4 columns and use column 2 (Holiday) for the name.
""")
    
    print("\n" + "="*80)
    print("RECOMMENDATIONS")
    print("="*80)
    print("""
1. FIX the regex in holiday_updater.py to capture 4 columns
2. AUDIT existing data in app.market_holidays - many entries are wrong
3. RE-RUN the holiday updater after fixing to correct the data
4. ADD validation to reject day names as holiday descriptions
""")


if __name__ == "__main__":
    asyncio.run(main())
