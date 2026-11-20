"""olist_dashboard_api: GET /dashboard -> every number the website dashboard needs, in one call.

Runs 6 read-only queries on Redshift Serverless through the Redshift Data API,
as the read-only database user stored in Secrets Manager.
Results are cached in memory for CACHE_SECONDS, so page refreshes do not re-query Redshift.

Environment variables:
  WORKGROUP      olistcap-wg
  DATABASE       dev
  SECRET_ARN     ARN of the read-only Redshift secret (olist/redshift-readonly)
  CACHE_SECONDS  optional, default 300
"""
import json
import os
import time

import boto3

rsd = boto3.client("redshift-data")
WG = os.environ["WORKGROUP"]
DB = os.environ["DATABASE"]
SECRET = os.environ["SECRET_ARN"]
CACHE_SECONDS = int(os.environ.get("CACHE_SECONDS", "300"))

QUERIES = {
    "kpis": """
        SELECT s.revenue, s.orders, o.avg_delivery_days, o.late_pct
        FROM (SELECT SUM(price) AS revenue, COUNT(DISTINCT order_id) AS orders
              FROM olist.fact_sales) s
        CROSS JOIN
             (SELECT AVG(delivery_days::float) AS avg_delivery_days,
                     AVG(is_late::float)       AS late_pct
              FROM olist.fact_orders) o""",
    "monthly": """
        SELECT cal_year, cal_month, revenue, items_sold
        FROM olist.mv_monthly_sales
        ORDER BY cal_year, cal_month""",
    "states": """
        SELECT c.customer_state AS state, COUNT(*) AS orders,
               SUM(o.items_value) AS revenue, AVG(o.is_late::float) AS late_pct
        FROM olist.fact_orders o
        JOIN olist.dim_customer c ON o.customer_key = c.customer_key
        GROUP BY c.customer_state
        ORDER BY orders DESC""",
    "categories": """
        SELECT COALESCE(p.category_en, 'unknown') AS category, SUM(s.price) AS revenue,
               COUNT(*) AS items
        FROM olist.fact_sales s
        JOIN olist.dim_product p ON s.product_key = p.product_key
        GROUP BY 1
        ORDER BY revenue DESC
        LIMIT 10""",
    "payments": """
        SELECT t.payment_type, COUNT(*) AS payments, SUM(f.payment_value) AS value
        FROM olist.fact_payments f
        JOIN olist.dim_payment_type t ON f.payment_type_key = t.payment_type_key
        GROUP BY t.payment_type
        ORDER BY payments DESC""",
    "sources": """
        SELECT data_source, COUNT(*) AS orders
        FROM olist.fact_orders
        GROUP BY data_source
        ORDER BY orders DESC""",
}

NUMERIC_TYPES = {"numeric", "decimal", "float4", "float8", "int2", "int4", "int8"}
_cache = {"at": 0.0, "body": None}


def _value(field, type_name):
    """Turn one Data API field into a plain Python value."""
    if field.get("isNull"):
        return None
    value = next(iter(field.values()))
    if type_name in NUMERIC_TYPES and isinstance(value, str):  # decimals arrive as text
        return float(value)
    return value


def _rows(statement_id):
    result = rsd.get_statement_result(Id=statement_id)
    cols = [(c["name"], c["typeName"]) for c in result["ColumnMetadata"]]
    return [{name: _value(f, t) for (name, t), f in zip(cols, rec)} for rec in result["Records"]]


def run_all():
    """Start every query at once, then wait for all of them (faster than one by one)."""
    ids = {name: rsd.execute_statement(WorkgroupName=WG, Database=DB, SecretArn=SECRET,
                                       Sql=sql)["Id"]
           for name, sql in QUERIES.items()}
    pending, deadline = dict(ids), time.time() + 25
    while pending:
        if time.time() > deadline:
            raise TimeoutError(f"queries still running: {list(pending)}")
        time.sleep(0.5)
        for name, sid in list(pending.items()):
            d = rsd.describe_statement(Id=sid)
            if d["Status"] == "FINISHED":
                del pending[name]
            elif d["Status"] in ("FAILED", "ABORTED"):
                raise RuntimeError(f"{name}: {d.get('Error')}")
    data = {name: _rows(sid) for name, sid in ids.items()}
    data["kpis"] = data["kpis"][0] if data["kpis"] else {}
    data["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return data


def lambda_handler(event, context):
    try:
        if _cache["body"] is None or time.time() - _cache["at"] > CACHE_SECONDS:
            _cache["body"] = json.dumps(run_all())
            _cache["at"] = time.time()
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": _cache["body"]}
    except Exception as e:  # shown in the website and in CloudWatch logs
        print(f"ERROR {e}")
        return {"statusCode": 500, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": str(e)})}
