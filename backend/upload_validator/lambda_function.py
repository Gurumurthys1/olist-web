"""olist_upload_validator: checks a CSV uploaded from the website, then hands it to the pipeline.

Trigger: S3 "object created" on s3://<BUCKET>/raw/uploads_incoming/  (suffix .csv)
The file arrives as raw/uploads_incoming/<table>/<upload_id>.csv  - one file = one Olist table.

The CSV has the same columns as the original Olist file of that table (see TABLES below).
Checks, row by row:
  - required columns present, formats (ids, dates, numbers, zip codes, states), allowed values
  - table rules (for example: a delivered order needs a delivery date)
  - no duplicate key inside the file
  - references exist: customer / product / seller / order / category must already be in
    Redshift OR in an earlier website upload (so you can upload a new customer, then its order)
If the key already exists, the uploaded row REPLACES the old one when the pipeline runs (update).

All rows valid -> raw/upload_<table>/upload_id=<id>/data.jsonl, which Glue job 1 reads with
data_source = 'upload'. One bad row rejects the whole file. The result goes to DynamoDB.
Then, if PIPELINE_ARN is set, the pipeline starts by itself (Redshift + QuickSight update).
If a run is already going, the upload waits; the pipeline's last step starts one more run.

Environment variables:
  TABLE         olist_uploads
  WORKGROUP     olistcap-wg
  DATABASE      dev
  SECRET_ARN    ARN of the read-only Redshift secret (olist/redshift-readonly)
  PIPELINE_ARN  ARN of the olistcap_pipeline state machine (optional: empty = no auto start)
"""
import csv
import io
import json
import os
import re
import time
import urllib.parse
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import boto3

s3 = boto3.client("s3")
rsd = boto3.client("redshift-data")
sfn = boto3.client("stepfunctions")
DDB = boto3.resource("dynamodb").Table(os.environ["TABLE"])

MAX_ROWS = 1000
STATUSES = ["created", "approved", "invoiced", "processing", "shipped", "delivered",
            "canceled", "unavailable"]
PAYMENT_TYPES = ["credit_card", "boleto", "voucher", "debit_card", "not_defined"]
STATES = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
          "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]


def col(name, kind, required=False, **rules):
    return {"name": name, "kind": kind, "required": required, **rules}


# The columns of every table, exactly as in the original Olist CSV files.
# kind: id (32 hex) | text | int | num | ts (date/time) | zip | state | enum | category
TABLES = {
    "orders": {"key": ["order_id"], "cols": [
        col("order_id", "id", True),
        col("customer_id", "id", True, ref="customer"),
        col("order_status", "enum", True, values=STATUSES),
        col("order_purchase_timestamp", "ts", True),
        col("order_approved_at", "ts"),
        col("order_delivered_carrier_date", "ts"),
        col("order_delivered_customer_date", "ts"),
        col("order_estimated_delivery_date", "ts")]},
    "order_items": {"key": ["order_id", "order_item_id"], "cols": [
        col("order_id", "id", True, ref="order"),
        col("order_item_id", "int", True, min=1, max=100),
        col("product_id", "id", True, ref="product"),
        col("seller_id", "id", True, ref="seller"),
        col("shipping_limit_date", "ts"),
        col("price", "num", True, min=0.01, max=100000),
        col("freight_value", "num", True, min=0, max=10000)]},
    "payments": {"key": ["order_id", "payment_sequential"], "cols": [
        col("order_id", "id", True, ref="order"),
        col("payment_sequential", "int", True, min=1, max=50),
        col("payment_type", "enum", True, values=PAYMENT_TYPES),
        col("payment_installments", "int", True, min=0, max=24),
        col("payment_value", "num", True, min=0, max=100000)]},
    "reviews": {"key": ["review_id", "order_id"], "cols": [
        col("review_id", "id", True),
        col("order_id", "id", True, ref="order"),
        col("review_score", "int", True, min=1, max=5),
        col("review_comment_title", "text"),
        col("review_comment_message", "text"),
        col("review_creation_date", "ts", True),
        col("review_answer_timestamp", "ts")]},
    "customers": {"key": ["customer_id"], "cols": [
        col("customer_id", "id", True),
        col("customer_unique_id", "id", True),
        col("customer_zip_code_prefix", "zip", True),
        col("customer_city", "text", True),
        col("customer_state", "state", True)]},
    "sellers": {"key": ["seller_id"], "cols": [
        col("seller_id", "id", True),
        col("seller_zip_code_prefix", "zip", True),
        col("seller_city", "text", True),
        col("seller_state", "state", True)]},
    "products": {"key": ["product_id"], "cols": [
        col("product_id", "id", True),
        col("product_category_name", "category", True, ref="category"),
        col("product_name_lenght", "int", min=0, max=1000),
        col("product_description_lenght", "int", min=0, max=10000),
        col("product_photos_qty", "int", min=0, max=50),
        col("product_weight_g", "int", min=0, max=100000),
        col("product_length_cm", "int", min=0, max=500),
        col("product_height_cm", "int", min=0, max=500),
        col("product_width_cm", "int", min=0, max=500)]},
    "category_translation": {"key": ["product_category_name"], "cols": [
        col("product_category_name", "category", True),
        col("product_category_name_english", "category", True)]},
    "geolocation": {"key": [], "cols": [
        col("geolocation_zip_code_prefix", "zip", True),
        col("geolocation_lat", "num", True, min=-34, max=6),
        col("geolocation_lng", "num", True, min=-74, max=-34),
        col("geolocation_city", "text", True),
        col("geolocation_state", "state", True)]},
}

# where each kind of reference is looked up: Redshift (table, column) and earlier uploads
REFS = {
    "customer": ("olist.dim_customer", "customer_id", "customers", "customer_id"),
    "product": ("olist.dim_product", "product_id", "products", "product_id"),
    "seller": ("olist.dim_seller", "seller_id", "sellers", "seller_id"),
    "order": ("olist.fact_orders", "order_id", "orders", "order_id"),
    "category": ("olist.dim_product", "category_pt", "category_translation", "product_category_name"),
}

ID = re.compile(r"^[0-9a-f]{32}$")
CATEGORY = re.compile(r"^[a-z0-9_]{1,60}$")
TS_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
              "%Y-%m-%d"]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def set_status(upload_id, status, message, **extra):
    names = {"#s": "status", "#m": "message", "#u": "updated_at"}
    values = {":s": status, ":m": message, ":u": now()}
    sets = ["#s = :s", "#m = :m", "#u = :u"]
    for i, (k, v) in enumerate(extra.items()):
        names[f"#x{i}"], values[f":x{i}"] = k, v
        sets.append(f"#x{i} = :x{i}")
    DDB.update_item(Key={"upload_id": upload_id}, UpdateExpression="SET " + ", ".join(sets),
                    ExpressionAttributeNames=names, ExpressionAttributeValues=values)


def parse_ts(text):
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def convert(c, raw):
    """One cell -> (clean value, error message or None)."""
    value = raw.strip()
    if value == "":
        return None, (f"{c['name']} is required" if c["required"] else None)
    kind = c["kind"]
    if kind == "id":
        value = value.lower()
        return value, None if ID.match(value) else f"{c['name']} must be 32 characters 0-9 / a-f"
    if kind == "category":
        value = value.lower().replace(" ", "_")
        return value, None if CATEGORY.match(value) else f"{c['name']} may only use a-z, 0-9 and _"
    if kind == "text":
        return re.sub(r"\s+", " ", value)[:500], None
    if kind == "enum":
        value = value.lower()
        return value, None if value in c["values"] else f"{c['name']} must be one of {', '.join(c['values'])}"
    if kind == "state":
        value = value.upper()
        return value, None if value in STATES else f"{c['name']} must be a Brazilian state code like SP"
    if kind == "zip":
        digits = value.split(".")[0]
        if not digits.isdigit() or len(digits) > 5:
            return value, f"{c['name']} must be up to 5 digits, like 01310"
        return digits.zfill(5), None
    if kind == "ts":
        dt = parse_ts(value)
        if not dt:
            return value, f"{c['name']} must look like 2018-10-25 14:30:00"
        if dt > datetime.utcnow() + timedelta(days=400):
            return value, f"{c['name']} is too far in the future"
        return dt.strftime("%Y-%m-%d %H:%M:%S"), None
    if kind in ("int", "num"):
        try:
            number = Decimal(value)
        except InvalidOperation:
            return value, f"{c['name']} must be a number"
        if kind == "int" and number != number.to_integral_value():
            return value, f"{c['name']} must be a whole number"
        if not (Decimal(str(c.get("min", -1e12))) <= number <= Decimal(str(c.get("max", 1e12)))):
            return value, f"{c['name']} must be between {c.get('min')} and {c.get('max')}"
        return (int(number) if kind == "int" else str(number)), None
    return value, None


def table_rules(table, r):
    """Checks that need more than one column."""
    errs = []
    if table == "orders":
        purchase = r["order_purchase_timestamp"]
        for c in ("order_approved_at", "order_delivered_carrier_date",
                  "order_delivered_customer_date", "order_estimated_delivery_date"):
            if purchase and r.get(c) and r[c][:10] < purchase[:10]:
                errs.append(f"{c} is before the purchase date")
        if purchase and purchase > now().replace("T", " ")[:19]:
            errs.append("order_purchase_timestamp is in the future")
        if r["order_status"] == "delivered" and not r.get("order_delivered_customer_date"):
            errs.append("a delivered order needs order_delivered_customer_date")
    if table == "reviews" and r.get("review_answer_timestamp") and r.get("review_creation_date") \
            and r["review_answer_timestamp"][:10] < r["review_creation_date"][:10]:
        errs.append("review_answer_timestamp is before review_creation_date")
    return errs


def check_rows(table, rows):
    """Returns (clean rows, errors)."""
    spec = TABLES[table]
    clean, errors, seen = [], [], {}
    for n, row in enumerate(rows, start=2):  # row 1 is the header
        out, row_errs = {}, []
        for c in spec["cols"]:
            value, err = convert(c, row.get(c["name"], ""))
            out[c["name"]] = value
            if err:
                row_errs.append(err)
        if not row_errs:
            row_errs = table_rules(table, out)
        if not row_errs and spec["key"]:
            key = tuple(out[k] for k in spec["key"])
            if key in seen:
                row_errs.append(f"same {' + '.join(spec['key'])} as row {seen[key]}")
            seen[key] = n
        errors += [f"row {n}: {e}" for e in row_errs]
        clean.append(out)
    return clean, errors


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


def uploaded_values(bucket, table, column):
    """Values of one column in every earlier website upload of that table (not loaded yet, maybe)."""
    values, token = set(), None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": f"raw/upload_{table}/"}
        if token:
            kwargs["ContinuationToken"] = token
        page = s3.list_objects_v2(**kwargs)
        for obj in page.get("Contents", []):
            body = s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read().decode("utf-8")
            for line in body.splitlines():
                if line.strip():
                    values.add(json.loads(line).get(column))
        if not page.get("IsTruncated"):
            return values
        token = page["NextContinuationToken"]


def check_refs(bucket, table, rows):
    """Every referenced id must exist in Redshift or in an earlier upload.
    Ids and category names were already checked against strict patterns, so they are safe in SQL."""
    wanted = {}
    for c in TABLES[table]["cols"]:
        if c.get("ref"):
            wanted.setdefault(c["ref"], set()).update(r[c["name"]] for r in rows if r[c["name"]])
    if not wanted:
        return []
    parts = []
    for ref, vals in wanted.items():
        rs_table, rs_col = REFS[ref][:2]
        in_list = ",".join(f"'{v}'" for v in sorted(vals))
        parts.append(f"SELECT DISTINCT '{ref}', {rs_col} FROM {rs_table} WHERE {rs_col} IN ({in_list})")
    found = {ref: set() for ref in wanted}
    for ref, value in run_sql("\nUNION ALL ".join(parts)):
        found[ref].add(value)

    errors = []
    for ref, vals in wanted.items():
        missing = vals - found[ref]
        if missing:  # maybe uploaded earlier from the website and not in Redshift yet
            missing -= uploaded_values(bucket, *REFS[ref][2:])
        for m in sorted(missing):
            errors.append(f"{ref} '{m}' does not exist (upload it first in the {REFS[ref][2]} table)")
    return errors


def read_csv(text):
    reader = csv.DictReader(io.StringIO(text))
    header = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
    reader.fieldnames = header
    rows = [{k: (v or "") for k, v in r.items() if k}
            for r in reader if any((v or "").strip() for v in r.values() if isinstance(v, str))]
    return header, rows


def validate(bucket, key):
    parts = key.split("/")
    upload_id, table = parts[-1].removesuffix(".csv"), parts[-2]
    set_status(upload_id, "VALIDATING", "Checking the file")
    if table not in TABLES:
        set_status(upload_id, "REJECTED", f"Unknown table '{table}'", errors=[])
        return

    text = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8-sig", "replace")
    header, rows = read_csv(text)
    required = [c["name"] for c in TABLES[table]["cols"] if c["required"]]
    missing = [c for c in required if c not in header]
    if missing:
        set_status(upload_id, "REJECTED", f"Missing columns: {', '.join(missing)}",
                   errors=[f"the header row of a {table} file must contain: "
                           + ", ".join(c["name"] for c in TABLES[table]["cols"])])
        return
    if not rows:
        set_status(upload_id, "REJECTED", "The file has no data rows", errors=[])
        return
    if len(rows) > MAX_ROWS:
        set_status(upload_id, "REJECTED", f"Too many rows ({len(rows)}); the limit is {MAX_ROWS}",
                   errors=[], row_count=len(rows))
        return

    clean, errors = check_rows(table, rows)
    if not errors:
        errors = check_refs(bucket, table, clean)
    if errors:
        set_status(upload_id, "REJECTED", f"{len(errors)} problem(s) found; nothing was loaded",
                   errors=errors[:20], row_count=len(rows))
        return

    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in clean) + "\n"
    s3.put_object(Bucket=bucket, Key=f"raw/upload_{table}/upload_id={upload_id}/data.jsonl",
                  Body=body.encode("utf-8"), ContentType="application/x-ndjson")
    set_status(upload_id, "READY", f"Valid. {start_pipeline()}", errors=[], row_count=len(clean))


def start_pipeline():
    """Start the pipeline unless it is already running. Two uploads in the same 5 minutes get the
    same run name, so Step Functions starts only one run for them."""
    arn = os.environ.get("PIPELINE_ARN", "")
    if not arn:
        return "It will be loaded into Redshift by the next pipeline run"
    try:
        if sfn.list_executions(stateMachineArn=arn, statusFilter="RUNNING", maxResults=1)["executions"]:
            return "The pipeline is busy; this upload loads in the run that follows it"
        window = int(time.time() // 300)
        sfn.start_execution(stateMachineArn=arn, name=f"upload-{window}",
                            input=json.dumps({"trigger": "upload"}))
        return "Loading into Redshift now (pipeline started, about 10-15 minutes)"
    except sfn.exceptions.ExecutionAlreadyExists:
        return "Loading into Redshift now (pipeline started, about 10-15 minutes)"
    except Exception as e:  # the data is safe; the nightly run will load it
        print(f"could not start the pipeline: {e}")
        return "It will be loaded into Redshift by the next pipeline run"


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
