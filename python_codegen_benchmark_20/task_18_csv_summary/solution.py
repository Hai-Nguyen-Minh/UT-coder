import csv
import io
from decimal import Decimal, InvalidOperation

def summarize_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("missing header")
    normalized = [name.strip() for name in reader.fieldnames]
    if "category" not in normalized or "amount" not in normalized:
        raise ValueError("required headers: category, amount")
    mapping = dict(zip(reader.fieldnames, normalized))
    result = {}
    for raw_row in reader:
        if not raw_row or all((v is None or not v.strip()) for v in raw_row.values()):
            continue
        row = {mapping[k]: v for k, v in raw_row.items()}
        category = (row.get("category") or "").strip()
        amount_text = (row.get("amount") or "").strip()
        if not category:
            raise ValueError("empty category")
        try:
            amount = Decimal(amount_text)
        except (InvalidOperation, ValueError):
            raise ValueError("invalid amount")
        result[category] = result.get(category, Decimal("0")) + amount
    return result
