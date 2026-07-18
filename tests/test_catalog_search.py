from app.services.catalog_search import prefix_tsquery


def test_prefix_tsquery_english():
    assert prefix_tsquery("Titanic II") == "Titanic:* & II:*"


def test_prefix_tsquery_strips_punctuation():
    assert prefix_tsquery("  lock-out!!  ") == "lock:* & out:*"


def test_prefix_tsquery_khmer():
    assert prefix_tsquery("វីរបុរសឈិនឡុង") == "វីរបុរសឈិនឡុង:*"


def test_prefix_tsquery_empty():
    assert prefix_tsquery("   ") is None
    assert prefix_tsquery("!!!") is None
