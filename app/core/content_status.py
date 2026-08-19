VALID_CONTENT_STATUSES = frozenset({"draft", "review", "scheduled", "published"})


def validate_content_status(status: str) -> None:
    if status not in VALID_CONTENT_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_CONTENT_STATUSES)}")
