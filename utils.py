import math


def compare_result_rows(actual, expected, *, ordered):
    """Compare fixture results without discarding duplicate rows or ranked order."""
    actual = [list(row) for row in actual]
    if not ordered:
        actual, expected = sorted(actual, key=repr), sorted(expected, key=repr)
    if len(actual) != len(expected):
        return False
    for actual_row, expected_row in zip(actual, expected):
        if len(actual_row) != len(expected_row):
            return False
        for value, reference in zip(actual_row, expected_row):
            if isinstance(value, (float, int)) and isinstance(reference, (float, int)):
                if not math.isclose(value, reference, rel_tol=1e-8, abs_tol=1e-8):
                    return False
            elif value != reference:
                return False
    return True


def extract_text(content):
    """
    Gemini's chat responses can come back as either a plain string
    or a list of content blocks. This normalizes either shape into
    plain displayable text.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts) if parts else str(content)
    return str(content)
