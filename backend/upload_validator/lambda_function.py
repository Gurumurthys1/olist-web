"""olist_upload_validator: checks a CSV uploaded from the website, then hands it to the pipeline.

Trigger: S3 "object created" on s3://<BUCKET>/raw/uploads_incoming/  (suffix .csv)

CSV columns (one row per order item; rows with the same order_id form one order):
  required  order_id, customer_id, order_purchase_timestamp, product_id, seller_id,
            price, freight_value, payment_type
  optional  order_status (default delivered), order_estimated_delivery_date (default +20 days),
            order_delivered_customer_date, payment_installments (default 1)

Checks: column names, formats, dates, numbers, allowed values, the same order details on every
row of one order, and (in Redshift) that the customer / product / seller exist and that the
order_id is new.

If every row is valid, writes JSON Lines that Glue job 1 reads with data_source = 'upload':
  raw/upload_orders/upload_id=<id>/data.jsonl
  raw/upload_order_items/upload_id=<id>/data.jsonl
  raw/upload_payments/upload_id=<id>/data.jsonl
One bad row rejects the whole file (nothing half-loaded). The result goes to DynamoDB.

Environment variables:
  TABLE       olist_uploads
  WORKGROUP   olistcap-wg
  DATABASE    dev
  SECRET_ARN  ARN of the read-only Redshift secret (olist/redshift-readonly)
"""
import csv
import io
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from decimal import Decimal

import boto3

s3 = boto3.client("s3")
rsd = boto3.client("redshift-data")
TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE"])

MAX_ROWS = 500
REQUIRED = ["order_id", "customer_id", "order_purchase_timestamp", "product_id", "seller_id",
            "price", "freight_value", "payment_type"]
OPTIONAL = ["order_status", "order_estimated_delivery_date", "order_delivered_customer_date",
            "payment_installments"]
STATUSES = {"created", "approved", "invoiced", "processing", "shipped", "delivered",
            "canceled", "unavailable"}
PAYMENT_TYPES = {"credit_card", "boleto", "voucher", "debit_card"}
ORDER_FIELDS = ["customer_id", "order_status", "order_purchase_timestamp",
                "order_estimated_delivery_date", "order_delivered_customer_date",
                "payment_type", "payment_installments"]
ID = re.compile(r"^[0-9a-f]{32}$")  # Olist ids: 32 lowercase hex characters
TS_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
              "%Y-%m-%d"]


def parse_ts(text):
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def set_status(upload_id, status, message, **extra):
    names = {"#s": "status", "#m": "message", "#u": "updated_at"}
    values = {":s": status, ":m": message, ":u": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    sets = ["#s = :s", "#m = :m", "#u = :u"]
    for i, (k, v) in enumerate(extra.items()):
        names[f"#x{i}"], values[f":x{i}"] = k, v
        sets.append(f"#x{i} = :x{i}")
    TABLE.update_item(Key={"upload_id": upload_id}, UpdateExpression="SET " + ", ".join(sets),
                      ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def check_rows(rows):
    """Format checks. Returns (orders, errors); orders = {order_id: {"order": {...}, "items": [...]}}."""
    errors, orders = [], {}
    for n, row in enumerate(rows, start=2):  # row 1 is the header
        def bad(msg):
            errors.append(f"row {n}: {msg}")

        for col in REQUIRED:
            if not row.get(col):
                bad(f"{col} is empty")
        if any(not row.get(c) for c in REQUIRED):
            continue

        for col in ("order_id", "customer_id", "product_id", "seller_id"):
            if not ID.match(row[col]):
                bad(f"{col} must be 32 characters 0-9 / a-f (got '{row[col][:40]}')")

        status = (row.get("order_status") or "delivered").lower()
        if status not in STATUSES:
            bad(f"order_status '{status}' is not one of {sorted(STATUSES)}")

        purchase = parse_ts(row["order_purchase_timestamp"])
        if not purchase:
            bad("order_purchase_timestamp must look like 2018-10-25 14:30:00")
        elif purchase > datetime.utcnow() + timedelta(days=1):
            bad("order_purchase_timestamp is in the future")
        estimated = (parse_ts(row["order_estimated_delivery_date"])
                     if row.get("order_estimated_delivery_date")
                     else purchase and purchase + timedelta(days=20))
        if row.get("order_estimated_delivery_date") and not estimated:
            bad("order_estimated_delivery_date is not a valid date")
        delivered = None
        if row.get("order_delivered_customer_date"):
            delivered = parse_ts(row["order_delivered_customer_date"])
            if not delivered:
                bad("order_delivered_customer_date is not a valid date")
        if purchase and delivered and delivered < purchase:
            bad("order_delivered_customer_date is before the purchase")
        if purchase and estimated and estimated < purchase:
            bad("order_estimated_delivery_date is before the purchase")
        if status == "delivered" and not delivered:
            bad("a delivered order needs order_delivered_customer_date")

        try:
            price, freight = Decimal(row["price"]), Decimal(row["freight_value"])
            if not (Decimal("0") < price <= Decimal("100000")):
                bad("price must be between 0.01 and 100000")
            if not (Decimal("0") <= freight <= Decimal("10000")):
                bad("freight_value must be between 0 and 10000")
        except Exception:
            bad("price and freight_value must be numbers like 129.90")
            price = freight = None

        ptype = row["payment_type"].lower()
        if ptype not in PAYMENT_TYPES:
            bad(f"payment_type '{ptype}' is not one of {sorted(PAYMENT_TYPES)}")
        inst = row.get("payment_installments") or "1"
        if not inst.isdigit() or not 1 <= int(inst) <= 24:
            bad("payment_installments must be a whole number from 1 to 24")

        if errors and errors[-1].startswith(f"row {n}:"):
            continue
        order = {"customer_id": row["customer_id"], "order_status": status,
                 "order_purchase_timestamp": fmt_ts(purchase),
                 "order_estimated_delivery_date": fmt_ts(estimated),
                 "order_delivered_customer_date": fmt_ts(delivered),
                 "payment_type": ptype, "payment_installments": int(inst)}
        entry = orders.setdefault(row["order_id"], {"order": order, "items": []})
        diff = [f for f in ORDER_FIELDS if entry["order"][f] != order[f]]
        if diff:
            bad(f"order {row['order_id'][:8]}… has different {', '.join(diff)} than its first row")
            continue
        entry["items"].append({"product_id": row["product_id"], "seller_id": row["seller_id"],
                               "price": price, "freight_value": freight})
    return orders, errors


def run_sql(sql):
    sid = rsd.execute_statement(WorkgroupName=os.environ["WORKGROUP"],
                                Database=os.environ["DATABASE"],
                                SecretArn=os.environ["SECRET_ARN"], Sql=sql)["Id"]
    deadline = time.time() + 60
    while True:
        d = rsd.describe_statement(Id=sid)
        if d["Status"] == "FINISHED":
            break
        if d["Status"] in ("FAILED", "ABORTED"):
            raise RuntimeError(f"Redshift check failed: {d.get('Error')}")
        if time.time() > deadline:
            raise TimeoutError("Redshift check took too long")
        time.sleep(0.5)
    if not d.get("HasResultSet"):
        return []
    return [[next(iter(f.values())) for f in rec]
            for rec in rsd.get_statement_result(Id=sid)["Records"]]


def check_in_redshift(orders):
    """Customers, products and sellers must exist; order ids must be new.
    Every id was already checked to be 32 hex characters, so it is safe inside the SQL."""
    ids = {"customer": {o["order"]["customer_id"] for o in orders.values()},
           "product": {i["product_id"] for o in orders.values() for i in o["items"]},
           "seller": {i["seller_id"] for o in orders.values() for i in o["items"]},
           "order": set(orders)}
    lists = {k: ",".join(f"'{v}'" for v in sorted(vals)) for k, vals in ids.items()}
    sql = f"""
        SELECT DISTINCT 'customer', customer_id FROM olist.dim_customer WHERE customer_id IN ({lists['customer']})
        UNION ALL SELECT DISTINCT 'product', product_id FROM olist.dim_product WHERE product_id IN ({lists['product']})
        UNION ALL SELECT DISTINCT 'seller', seller_id FROM olist.dim_seller WHERE seller_id IN ({lists['seller']})
        UNION ALL SELECT DISTINCT 'order', order_id FROM olist.fact_orders WHERE order_id IN ({lists['order']})"""
    found = {k: set() for k in ids}
    for kind, value in run_sql(sql):
        found[kind].add(value)

    errors = []
    for kind in ("customer", "product", "seller"):
        for missing in sorted(ids[kind] - found[kind]):
            errors.append(f"{kind}_id {missing} does not exist in Redshift")
    for existing in sorted(found["order"]):
        errors.append(f"order_id {existing} already exists (use a new order_id)")
    return errors


def write_jsonl(bucket, key, rows):
    body = "\n".join(json.dumps(r, default=str) for r in rows) + "\n"
    s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"),
                  ContentType="application/x-ndjson")


def to_pipeline(bucket, upload_id, orders):
    """Same column names as the Olist tables, so Glue job 1 treats them like any other source."""
    o_rows, i_rows, p_rows = [], [], []
    for order_id, o in orders.items():
        order = o["order"]
        purchase = order["order_purchase_timestamp"]
        o_rows.append({"order_id": order_id, "customer_id": order["customer_id"],
                       "order_status": order["order_status"],
                       "order_purchase_timestamp": purchase, "order_approved_at": purchase,
                       "order_delivered_carrier_date": None,
                       "order_delivered_customer_date": order["order_delivered_customer_date"],
                       "order_estimated_delivery_date": order["order_estimated_delivery_date"]})
        total = Decimal("0")
        for n, item in enumerate(o["items"], start=1):
            i_rows.append({"order_id": order_id, "order_item_id": n,
                           "product_id": item["product_id"], "seller_id": item["seller_id"],
                           "shipping_limit_date": purchase,
                           "price": item["price"], "freight_value": item["freight_value"]})
            total += item["price"] + item["freight_value"]
        p_rows.append({"order_id": order_id, "payment_sequential": 1,
                       "payment_type": order["payment_type"],
                       "payment_installments": order["payment_installments"],
                       "payment_value": total})
    for table, rows in (("orders", o_rows), ("order_items", i_rows), ("payments", p_rows)):
        write_jsonl(bucket, f"raw/upload_{table}/upload_id={upload_id}/data.jsonl", rows)
    return len(o_rows), len(i_rows), sum((p["payment_value"] for p in p_rows), Decimal("0"))


def validate(bucket, key):
    upload_id = key.rsplit("/", 1)[-1].removesuffix(".csv")
    set_status(upload_id, "VALIDATING", "Checking the file")

    text = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8-sig", "replace")
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        set_status(upload_id, "REJECTED", f"Missing columns: {', '.join(missing)}",
                   errors=[f"the header row must contain: {', '.join(REQUIRED)}"])
        return
    reader.fieldnames = header
    rows = [{k: (v or "").strip() for k, v in r.items() if k} for r in reader
            if any((v or "").strip() for v in r.values() if isinstance(v, str))]
    if not rows:
        set_status(upload_id, "REJECTED", "The file has no data rows", errors=[])
        return
    if len(rows) > MAX_ROWS:
        set_status(upload_id, "REJECTED", f"Too many rows ({len(rows)}); the limit is {MAX_ROWS}",
                   errors=[], row_count=len(rows))
        return

    orders, errors = check_rows(rows)
    if not errors:
        errors = check_in_redshift(orders)
    if errors:
        set_status(upload_id, "REJECTED", f"{len(errors)} problem(s) found; nothing was loaded",
                   errors=errors[:20], row_count=len(rows))
        return

    n_orders, n_items, total = to_pipeline(bucket, upload_id, orders)
    set_status(upload_id, "READY",
               "Valid. It will be loaded into Redshift by the next pipeline run",
               errors=[], row_count=len(rows), order_count=n_orders, item_count=n_items,
               total_value=total)


def lambda_handler(event, context):
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        try:
            validate(bucket, key)
        except Exception as e:
            print(f"ERROR {key}: {e}")
            upload_id = key.rsplit("/", 1)[-1].removesuffix(".csv")
            set_status(upload_id, "REJECTED", f"Validator error: {e}", errors=[str(e)[:300]])
    return {"ok": True}
