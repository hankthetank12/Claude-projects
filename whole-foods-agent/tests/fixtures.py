"""Synthetic receipt markup shaped exactly like the real emails.

Deliberately not a real receipt: same structure, invented order numbers and
products, so the suite carries no one's shopping history.
"""

RECEIPT_HTML = """
<html><head><style>.rio-card{color:#fff}.x{a:>b}</style></head><body>
<table><tr><td>August 23, 2026</td></tr>
<tr><td>Whole Foods Market - Example Street</td></tr>
<tr><td>Order #</td><td>113-0000000-0000001</td></tr>
<tr><td>Transaction Id</td><td>ABC123XYZ9</td></tr>
<tr><td>Payment Method(s)</td><td>Visa</td><td>*1234 &nbsp; $42.75</td></tr>
<tr><td>Subtotal</td><td>$44.06</td></tr>
<tr><td>Total Savings</td><td>-$1.49</td></tr>
<tr><td>Sales Tax</td><td>$0.18</td></tr>
<tr><td>Total</td><td>$42.75</td></tr>
</table>
<p>How was your trip?</p>
<div>Items Purchased: 11</div>
<div>
  <div>Organic Rainbow Carrot Bag, 32 OZ</div><div>Qty: 1 @ $3.69 each</div><div>$3.69</div>
  <div>Mitica 24 Month Aged Parmigiano Reggiano</div><div>Qty: 0.45 lb @ $26.99/lb</div><div>$12.15</div>
  <div>PRODUCE Organic Sweet Onion</div><div>Qty: 2.52 lb @ $2.99/lb</div><div>$7.53</div>
  <div>365 by Whole Foods Market Organic Cannellini Beans, 15.5 OZ</div><div>Qty: 3 @ $1.69 each</div><div>$5.07</div>
  <div>Kettle &amp; Fire Organic Chicken Broth, 32 OZ</div><div>Qty: 2 @ $5.29 each</div><div>$10.58</div>
  <div>Organic Red Raspberries, 6 Oz</div><div>Qty: 1 @ $4.99 each</div><div>$3.50</div><div>$1.49 promotions applied</div>
  <div>CUSTOMER SERVICES Bag Fee</div><div>Qty: 1 @ $0.00 each</div><div>$0.00</div>
  <div>Container Deposit Single Container Deposit</div><div>Qty: 1 @ $0.05 each</div><div>$0.05</div>
</div>
<!--[if mso]><a href="https://www.amazon.com/x?a=1&T=C&U=https%3A%2F%2Fwww.amazon.com%2Ffopo%3Fx%3D1>2" style="border:1px solid #FCD200;font-family:Ember">Track</a><![endif]-->
<a href="https://www.amazon.com/fopo/order-details">View All Items</a>
<div>&copy;2026 Amazon.com, Inc.</div>
</body></html>
"""

# A trip where the email listed only some of what was bought.
TRUNCATED_HTML = """
<html><body>
<div>September 7, 2026</div>
<div>Whole Foods Market - Example Street</div>
<div>Order #</div><div>113-0000000-0000002</div>
<div>Subtotal</div><div>$60.00</div>
<div>Total</div><div>$60.00</div>
<div>Items Purchased: 30</div>
<div>Organic Garlic, 3 CT</div><div>Qty: 1 @ $2.69 each</div><div>$2.69</div>
<div>Organic Green Cucumber</div><div>Qty: 3 @ $1.99 each</div><div>$5.97</div>
<div>View All Items</div>
</body></html>
"""

RECEIPT_TEXT = """September 7, 2026 Whole Foods Market - Example Street Order # 113-0000000-0000003

* Subtotal - $12.00

* Total - $12.00

Items Purchased: 3

Organic Garlic, 3 CT

PRODUCE Organic Rosemary, 0.75 OZ

CUSTOMER SERVICES Bag Fee

View All Items (https://www.amazon.com/fopo/order-details)
"""
