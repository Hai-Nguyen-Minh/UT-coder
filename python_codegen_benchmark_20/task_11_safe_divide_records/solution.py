def safe_divide_records(records):
    result = []
    for numerator, denominator in records:
        try:
            result.append(numerator / denominator)
        except ZeroDivisionError:
            result.append("division_by_zero")
        except (TypeError, ValueError):
            result.append("invalid_operand")
    return result
