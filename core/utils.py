from decimal import Decimal, InvalidOperation


def fmt_qty(value):
    """Miqdorni ortiqcha nollarsiz: 5.000 -> '5', 1.250 -> '1.25', 10 -> '10'"""
    try:
        text = f'{Decimal(value or 0):f}'
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    return text.rstrip('0').rstrip('.') if '.' in text else text


def fmt_money(value):
    """12345.5 -> '12 346'"""
    try:
        return f'{Decimal(value or 0):,.0f}'.replace(',', ' ')
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
