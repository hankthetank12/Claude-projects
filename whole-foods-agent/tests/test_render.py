from datetime import date, timedelta

import pytest

from whole_foods_agent import basket, catalog as catalog_mod, render
from whole_foods_agent.cart import CartUnavailable, DeepLinkCart, get_adapter
from whole_foods_agent.model import LineItem, Order

START = date(2026, 1, 1)


@pytest.fixture
def proposal():
    orders = [
        Order(
            order_id=f"o{i}",
            ordered_on=START + timedelta(days=7 * i),
            items=[
                LineItem.from_raw("Organic Whole Milk, 59 FZ", quantity=1, unit="each", unit_price=6.99, line_total=6.99),
                LineItem.from_raw("PRODUCE Organic Sweet Onion", quantity=2.5, unit="lb", unit_price=2.99, line_total=7.48),
            ],
        )
        for i in range(5)
    ]
    catalog = catalog_mod.build(orders)
    last = max(s.last_bought for s in catalog.items.values())
    return basket.build(catalog, on_date=last + timedelta(days=7)), catalog


def test_text_lists_every_item_with_its_reasoning(proposal):
    prop, _ = proposal
    text = render.render_text(prop)
    assert "Organic Whole Milk" in text
    assert "Organic Sweet Onion" in text
    assert "about every 7 days" in text
    assert "Estimated total:" in text


def test_html_is_self_contained(proposal):
    prop, catalog = proposal
    page = render.render_html(prop, order_count=len(catalog.orders))
    assert page.startswith("<!doctype html>")
    # No external stylesheet, script or image requests.
    assert "<link" not in page
    assert "src=" not in page
    assert "<style>" in page and "<script>" in page


def test_html_shows_the_items_and_the_estimate(proposal):
    prop, catalog = proposal
    page = render.render_html(prop, order_count=len(catalog.orders))
    assert "Organic Whole Milk" in page
    assert f"${prop.estimated_total:.2f}" in page
    assert page.count('class="item"') == len(prop.lines)


def test_weighed_items_show_their_unit(proposal):
    prop, catalog = proposal
    page = render.render_html(prop, order_count=len(catalog.orders))
    assert "2.5 lb" in page


def test_names_are_escaped():
    page = render.render_html(
        basket.build(
            catalog_mod.build(
                [
                    Order(
                        order_id=f"o{i}",
                        ordered_on=START + timedelta(days=7 * i),
                        items=[
                            LineItem.from_raw(
                                "Ben & Jerry's <b>Ice Cream</b>",
                                quantity=1,
                                unit="each",
                                unit_price=5.0,
                                line_total=5.0,
                            )
                        ],
                    )
                    for i in range(3)
                ]
            ),
            on_date=START + timedelta(days=21),
        ),
        order_count=3,
    )
    assert "<b>Ice Cream</b>" not in page
    assert "&lt;b&gt;Ice Cream&lt;/b&gt;" in page


def test_search_links_point_at_the_whole_foods_storefront():
    url = render.search_url("Organic Sweet Onion")
    assert url.startswith("https://www.amazon.com/s?k=Organic+Sweet+Onion")
    assert render.WFM_BRAND_ID in url


def test_subject_summarises_the_order(proposal):
    prop, _ = proposal
    assert "items due" in render.subject(prop)


def test_deep_link_cart_resolves_every_line_without_adding_anything(proposal):
    prop, _ = proposal
    entries = DeepLinkCart().submit(prop.lines)
    assert len(entries) == len(prop.lines)
    assert all(entry.url for entry in entries)
    # It must never claim to have put something in a real basket.
    assert not any(entry.added for entry in entries)


def test_the_browser_cart_refuses_rather_than_pretending():
    with pytest.raises(CartUnavailable):
        get_adapter("browser").submit([])


def test_an_unknown_cart_back_end_is_rejected():
    with pytest.raises(CartUnavailable):
        get_adapter("telepathy")
