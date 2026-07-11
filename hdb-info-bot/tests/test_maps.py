from hdb_bot.maps import TOWN_CENTROIDS, nearest_town


def test_nearest_town_returns_exact_match_for_a_centroid():
    lat, lng = TOWN_CENTROIDS["BISHAN"]
    assert nearest_town(lat, lng) == "BISHAN"


def test_nearest_town_picks_closest_of_two_neighbours():
    # Somewhere between Bishan and Toa Payoh, but nudged toward Bishan.
    bishan = TOWN_CENTROIDS["BISHAN"]
    toa_payoh = TOWN_CENTROIDS["TOA PAYOH"]
    lat = bishan[0] * 0.8 + toa_payoh[0] * 0.2
    lng = bishan[1] * 0.8 + toa_payoh[1] * 0.2
    assert nearest_town(lat, lng) == "BISHAN"
