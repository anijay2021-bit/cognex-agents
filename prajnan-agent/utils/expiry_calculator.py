from datetime import date, timedelta

NSE_HOLIDAYS_2026 = [
    date(2026, 1, 26), date(2026, 3, 31), date(2026, 4, 14),
    date(2026, 4, 18), date(2026, 5, 1),  date(2026, 8, 15),
    date(2026, 10, 2), date(2026, 10, 22), date(2026, 11, 5),
    date(2026, 11, 26), date(2026, 12, 25),
]

def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    if d in NSE_HOLIDAYS_2026:
        return False
    return True

def get_weekly_expiry(reference_date: date = None) -> date:
    if reference_date is None:
        reference_date = date.today()
    days_to_tuesday = (1 - reference_date.weekday()) % 7
    tuesday = reference_date + timedelta(days=days_to_tuesday)
    if reference_date.weekday() > 1:
        tuesday = tuesday + timedelta(days=7)
    while not is_trading_day(tuesday):
        tuesday = tuesday - timedelta(days=1)
    return tuesday

def get_next_weekly_expiry(reference_date: date = None) -> date:
    if reference_date is None:
        reference_date = date.today()
    current = get_weekly_expiry(reference_date)
    return get_weekly_expiry(current + timedelta(days=1))

def get_monthly_expiry(reference_date: date = None) -> date:
    if reference_date is None:
        reference_date = date.today()

    def last_tuesday_of_month(year, month):
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        days_back = (last_day.weekday() - 1) % 7
        return last_day - timedelta(days=days_back)

    monthly = last_tuesday_of_month(reference_date.year, reference_date.month)
    while not is_trading_day(monthly):
        monthly = monthly - timedelta(days=1)

    if reference_date > monthly:
        if reference_date.month == 12:
            nm = date(reference_date.year + 1, 1, 1)
        else:
            nm = date(reference_date.year, reference_date.month + 1, 1)
        monthly = last_tuesday_of_month(nm.year, nm.month)
        while not is_trading_day(monthly):
            monthly = monthly - timedelta(days=1)

    return monthly

def get_expiry_dates() -> dict:
    today = date.today()
    weekly      = get_weekly_expiry(today)
    next_weekly = get_next_weekly_expiry(today)
    monthly     = get_monthly_expiry(today)
    return {
        "weekly":          weekly,
        "next_weekly":     next_weekly,
        "monthly":         monthly,
        "weekly_str":      weekly.strftime("%d-%b-%Y"),
        "next_weekly_str": next_weekly.strftime("%d-%b-%Y"),
        "monthly_str":     monthly.strftime("%d-%b-%Y"),
    }

if __name__ == "__main__":
    dates = get_expiry_dates()
    today = date.today()
    print(f"Today:          {today} ({today.strftime('%A')})")
    print(f"Weekly expiry:  {dates['weekly_str']} ({dates['weekly'].strftime('%A')})")
    print(f"Next weekly:    {dates['next_weekly_str']} ({dates['next_weekly'].strftime('%A')})")
    print(f"Monthly expiry: {dates['monthly_str']} ({dates['monthly'].strftime('%A')})")
