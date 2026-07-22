from app.tools.providers import find_nearby_doctors_impl


def test_sara_signature_sorted_by_distance():
    result = find_nearby_doctors_impl("M001")
    providers = result["providers"]
    assert result["member_plan"] == "Signature"
    distances = [p["distance_mi"] for p in providers]
    assert distances == sorted(distances)
    assert providers[0]["id"] == "P01"  # Dr. Rachel Torres, 0.4 mi, closest


def test_limit_is_respected():
    result = find_nearby_doctors_impl("M001", limit=3)
    assert len(result["providers"]) == 3


def test_out_of_network_plan_excluded():
    """Dr. Marcus Reed only accepts Signature/Choice -- James is on
    Advantage, so Reed should not appear in his in-network list."""
    result = find_nearby_doctors_impl("M003")
    ids = [p["id"] for p in result["providers"]]
    assert "P02" not in ids


def test_provider_name_lookup_in_network():
    result = find_nearby_doctors_impl("M003", provider_name="Torres")
    assert result["in_network"] is True
    assert result["provider"]["id"] == "P01"


def test_provider_name_lookup_out_of_network():
    result = find_nearby_doctors_impl("M001", provider_name="Warby Parker")
    assert result["in_network"] is False


def test_provider_name_no_match_returns_error():
    result = find_nearby_doctors_impl("M001", provider_name="Definitely Not A Real Provider")
    assert "error" in result
