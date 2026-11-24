import pytest

from coi.matching import match_client, normalize, similarity
from coi.models import Client, MatchStatus


def _client(id_, name):
    return Client(id=id_, name=name)


def test_normalize_drops_suffix_and_punctuation():
    assert normalize("Summit Roofing, LLC") == "summit roofing"
    assert normalize("A&B Roofing Inc.") == "a and b roofing"


def test_exact_match_ignoring_suffix(clients):
    result = match_client("Summit Roofing, LLC", clients)
    assert result.status is MatchStatus.MATCHED and result.client_id == "summit-roofing"


def test_unknown_name_is_not_found(clients):
    assert match_client("Lakeside Landscaping", clients).status is MatchStatus.NOT_FOUND


def test_blank_name_is_not_found(clients):
    assert match_client(None, clients).status is MatchStatus.NOT_FOUND
    assert match_client("   ", clients).status is MatchStatus.NOT_FOUND


def test_similar_clients_are_ambiguous_not_guessed():
    clients = [_client("a", "Summit Roofing LLC"), _client("b", "Summit Roofing and Siding Inc.")]
    result = match_client("Summit Roofing", clients)
    # "Summit Roofing" is exactly client a, so that one is fine...
    assert result.status is MatchStatus.MATCHED and result.client_id == "a"
    # ...but a vaguer name must go to a human.
    vague = match_client("Summit Roof", clients)
    assert vague.status is MatchStatus.AMBIGUOUS and vague.client_id is None
    assert {c.client_id for c in vague.candidates} == {"a", "b"}


def test_single_word_containment_is_not_enough():
    assert similarity("Summit", "Summit Roofing") < 0.9


@pytest.mark.parametrize("a,b", [("Smith Roofing", "Smith Plumbing")])
def test_different_trades_do_not_automatch(a, b):
    assert similarity(a, b) < 0.9
