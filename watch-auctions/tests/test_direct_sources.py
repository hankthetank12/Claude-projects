import json

from watch_auctions import houses
from watch_auctions.sources import auctionmethod, auctionninja, bidspirit, ctbids, shopgoodwill


def test_shopgoodwill_item_uses_store_name_and_pacific_time():
    it = {"itemId": 279009522, "title": "Antique ACME 14K Gold Filled Ladies Wristwatch", "sellerId": 144,
          "imageURL": "https://img.net/production/144\\Item\\a.jpeg", "startTime": "2026-09-30T18:32:13.263",
          "endTime": "2026-10-08T06:58:00", "currentPrice": 21.0, "numBids": 4}
    l = shopgoodwill.to_lot(it, {"companyName": "Heart of Texas Goodwill", "city": "Waco", "state": "TX"})
    assert (l.house, l.city, l.state) == ("Heart of Texas Goodwill", "Waco", "TX")
    assert l.url == "https://shopgoodwill.com/item/279009522"
    assert l.image == "https://img.net/production/144/Item/a.jpeg"
    assert l.ends_at == 1791467880  # 06:58 PDT = 13:58 UTC
    assert shopgoodwill.to_lot(it).house == "Goodwill store #144"


def test_ctbids_item():
    it = {"id": 5682363, "title": "Vintage Ladies Herna Rhinestone Watch", "saleid": 48474,
          "itemseourl": "Vintage-Ladies-Herna-Rhinestone-Watch", "city": "Toledo", "state": "Ohio",
          "displayimageurl": "https://image.ctbids.com/x.webp", "itemclosetime": "2026-10-08 22:53:00"}
    l = ctbids.to_lot(it)
    assert l.url == "https://ctbids.com/estate-sale/48474/item/5682363/Vintage-Ladies-Herna-Rhinestone-Watch"
    assert (l.state, l.ends_at) == ("OH", 1791499980)  # 6:53pm EDT; the sale "Ends 10/08 7PM"


def test_bidspirit_item():
    it = {"houseCode": "silvercityauctions", "id": "x", "idInApp": "236194", "name": "Rolex SS DateJust 36mm",
          "itemIndex": "12", "estimatedPrice": "$2,000 - $2,500", "imagesList": ["001.jpg"], "imagesBase": "236194"}
    auction = {"intKey": "81417", "name": "October Sale", "startTimeMillis": "1791471600000", "timedAuction": False}
    l = bidspirit.to_lot(it, auction, {"name": "Silver City Auctions", "city": "Findlay", "stateCode": "OH"})
    assert l.url.startswith("https://us.bidspirit.com/ui/lotPage/silvercityauctions/source/catalog/auction/81417/lot/236194/")
    assert l.image.endswith("/silvercityauctions/cloned-images/236194/001/a_ignore_q_80_w_400_h_400_c_fit_001.jpg")
    assert (l.estimate_low, l.estimate_high, l.starts_at, l.sale_type) == (2000, 2500, 1791471600, "live")


CARD = """<span>483 results</span>
<div class="iteam-result-box" id="MainItmID_5908_200364"><input type="hidden" id="time_left_dff_5908_200364" value="3600">
<img class="hi-new thumb" loading="lazy" src="https://pics/1.jpg">
<div class="hot-items-title"><a href="https://www.auctionninja.com/blackwell/product/omega-200364.html">Omega Seamaster &amp; Box</a></div>
<p id="CURBIDID_5908_200364" >$1,250.00</p>
<div class="hi-auction-company"><div class="hi-auction-company-title"><a href="https://www.auctionninja.com/blackwell" >Blackwell Auction Group</a></div><p>Cape Coral, FL</p>
</div>"""


def test_auctionninja_card():
    lots, total = auctionninja.parse_page(CARD, now=1000)
    assert total == 483 and len(lots) == 1
    l = lots[0]
    assert (l.title, l.house, l.city, l.state) == ("Omega Seamaster & Box", "Blackwell Auction Group", "Cape Coral", "FL")
    assert (l.current_bid, l.ends_at, l.image) == (1250.0, 4600, "https://pics/1.jpg")


def test_auctionmethod_item():
    house = {"name": "GWS Auctions", "url": "https://bid.gwsauctions.com", "city": "Agoura Hills", "state": "CA"}
    it = {"item_id": "61626", "title": "Rolex Day-Date 18K", "url": "https://bid.gwsauctions.com/item/61626",
          "current_bid": "1,200", "lot_number": "7", "end_time_unix": "1790416800", "thumb_url": "https://t/1.jpg"}
    l = auctionmethod.to_lot(it, {"title": "Hoard"}, house, house["url"])
    assert (l.source_id, l.current_bid, l.ends_at, l.state) == ("bid.gwsauctions.com:61626", 1200, 1790416800, "CA")


def test_add_house_detects_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(houses, "REGISTRY", tmp_path / "houses.json")
    monkeypatch.setattr(houses, "fetch", lambda url: '<script src="https://d3sachi1veog95.cloudfront.net/js/app.js">')
    entry, status = houses.add("bid.example-auctions.com", name="Example")
    assert status == "added" and entry["engine"] == "auctionmethod"
    assert json.loads((tmp_path / "houses.json").read_text())[0]["url"] == "https://bid.example-auctions.com"

    monkeypatch.setattr(houses, "fetch", lambda url: '<img src="https://image.invaluable.com/x.jpg">')
    _, status = houses.add("live.example.com")
    assert "already covered" in status


def test_bidwrangler_item():
    from watch_auctions.sources import bidwrangler
    it = {"id": 26140699, "name": "Omega Seamaster Automatic", "simple_id": "#1042",
          "scheduled_end_time_unix": 1791504180, "estimated_begin_time_unix": 1790269200,
          "images": [{"sm": "https://cdn/sm.jpg", "xs": "https://cdn/xs.jpg"}],
          "api_bidding_state": {"accepted_bid_count": 9, "high": {"amount": 225}}}
    auction = {"id": 169568, "name": "Home & Decor", "online_only": True, "company": {"name": "Alderfer Auction"},
               "location": {"city": "Hatfield", "state": "PA"}}
    l = bidwrangler.to_lot(it, auction, "bid.alderferauction.com")
    assert l.url == "https://bid.alderferauction.com/ui/auctions/169568/26140699"
    assert (l.house, l.city, l.state, l.lot_number) == ("Alderfer Auction", "Hatfield", "PA", "1042")
    assert (l.current_bid, l.bid_count, l.image, l.sale_type) == (225, 9, "https://cdn/sm.jpg", "timed")


def test_ebth_item():
    from watch_auctions.sources import ebth
    it = {"id": "14616916", "public_url": "/items/14616916-cartier-tank", "name": "Cartier Tank Vermeil Quartz Watch",
          "sale_ends_at": "2026-10-09T00:16:20.000Z", "bids_count": "37", "high_bid_amount": "1500",
          "main_image": "https://img/1.jpg", "pickup_city_state": "Blue Ash, OH"}
    l = ebth.to_lot(it)
    assert l.url == "https://www.ebth.com/items/14616916-cartier-tank"
    assert (l.city, l.state, l.current_bid, l.bid_count, l.ends_at) == ("Blue Ash", "OH", 1500, 37, 1791504980)


PR_PAGE = """<span>574 Results</span>
<a href="/l/rolex-datejust/18973774" class="listing-card" data-listing-id="18973774">
    <img type="" src="https://content.propertyroom.com/a.jpg" alt="" title="Rolex Datejust" />
    <div class="listing-title">Rolex Datejust 16234 Steel</div>
            <span class="listing-time" data-end="2026-10-09T22:30:00.0000000Z">1d 4h</span>
        <span class="listing-price">$1,410.00</span>
            <span class="listing-bids">23 bids</span>
</a>"""


def test_propertyroom_card():
    from watch_auctions.sources import propertyroom
    lots, total = propertyroom.parse_page(PR_PAGE)
    assert total == 574 and len(lots) == 1
    l = lots[0]
    assert (l.title, l.url, l.current_bid, l.bid_count) == (
        "Rolex Datejust 16234 Steel", "https://www.propertyroom.com/l/rolex-datejust/18973774", 1410, 23)
    assert l.ends_at == 1791585000
