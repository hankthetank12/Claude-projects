from watch_auctions.sources import invaluable, liveauctioneers

LA_ITEM = {
    "itemId": 241204719, "title": "Rolex Lady-Datejust 69173 Two-Tone Watch", "slug": "rolex-lady-datejust-69173",
    "sellerId": 9592, "catalogId": 432309, "photos": [1, 2], "imageVersion": 17, "sellerName": "Dover Jewelry",
    "sellerCity": "Miami", "sellerStateCode": "FL", "lotNumber": "0022", "catalogTitle": "Beyond the Ordinary",
    "isTimedAuction": False, "saleStartTs": 1791849600, "lotEndTimeEstimatedTs": 1791849660,
    "currency": "USD", "lowBidEstimate": 5500, "highBidEstimate": 6500, "leadingBid": 3250, "bidCount": 4,
}


def test_liveauctioneers_item():
    l = liveauctioneers.to_lot(LA_ITEM)
    assert l.url == "https://www.liveauctioneers.com/item/241204719_rolex-lady-datejust-69173"
    assert l.image.startswith("https://p1.liveauctioneers.com/9592/432309/241204719_1_m.jpg")
    assert (l.lot_number, l.sale_type, l.state, l.current_bid) == ("22", "live", "FL", 3250)


def test_liveauctioneers_skips_bulk_dealers_and_majors():
    payload = {"facets": [{"id": "auctionHouse", "options": [
        {"label": "Mynt Auctions", "id": "7804", "count": 6000},
        {"label": "Bonhams", "id": "1043", "count": 50},
        {"label": "Lark Mountain Auction Company", "id": "5", "count": 18}]}]}
    assert [i for i, _, _ in liveauctioneers.houses_to_skip(payload, 400)] == ["7804", "1043"]


def test_liveauctioneers_query_excludes_houses():
    p = liveauctioneers.search_params(2, ["7804"])
    assert p["options"]["auctionHouse"] == [{"exclude": ["7804"], "include": []}]
    assert p["options"]["countryCode"] == ["US"] and p["page"] == 2


def test_invaluable_hit():
    hit = {"objectID": "1", "lotRef": "E91DFE13A9", "lotTitle": "Omega Gold Filled Pocket Watch",
           "lotNumber": "1119", "houseName": "Clarke Auction Gallery", "location": "Larchmont, NY, US",
           "stateName": "New York", "photoPath": "clarke/1/2/a.jpg", "saleType": "Live",
           "dateTimeUTCUnix": 1791900000, "endTimeUTCUnix": 0, "currencyCode": "USD"}
    l = invaluable.to_lot(hit)
    assert l.url == "https://www.invaluable.com/auction-lot/omega-gold-filled-pocket-watch-1119-c-e91dfe13a9"
    assert l.image == "https://image.invaluable.com/housePhotos/clarke/1/2/a.jpg"
    assert (l.state, l.city, l.sale_type) == ("NY", "Larchmont", "live")


def test_invaluable_query_keeps_live_sales_without_end_time():
    q = invaluable.query(100, 200, 0, "Pocket Watches")
    assert q["numericFilters"][0] == ["endTimeUTCUnix>100", "endTimeUTCUnix=0"]
    assert "categoryName:Pocket Watches" in q["facetFilters"]
