"""olist_ask_data: answer a plain-English question about the Olist data.

Runs in YOUR account (where Redshift is). Bedrock is used from ANOTHER account (account B):
the Lambda borrows a role there with STS AssumeRole, so no access keys are copied anywhere.

  1. question + table schema -> Bedrock (account B) -> one SQL SELECT
  2. safety check: one statement, SELECT/WITH only, no write keywords, max 200 rows
  3. SQL -> Redshift, as the READ-ONLY database user
  4. rows -> Bedrock -> a short answer in plain English

Input:  API Gateway body {"question": "..."}  or a Lambda test event {"question": "..."}
Output: {"question", "sql", "columns", "rows", "answer"}

Environment variables:
  BEDROCK_ROLE_ARN  role in account B, e.g. arn:aws:iam::<B>:role/BedrockForOlist
  EXTERNAL_ID       the shared secret word written in that role's trust policy
  BEDROCK_REGION    region where account B has Bedrock, e.g. us-east-1
  MODEL_ID          e.g. amazon.nova-lite-v1:0  (or us.amazon.nova-lite-v1:0)
  WORKGROUP         olistcap-wg
  DATABASE          dev
  SECRET_ARN        ARN of the read-only Redshift secret (olist/redshift-readonly)
"""
import json
import os
import re
import time

import boto3

rsd = boto3.client("redshift-data")
sts = boto3.client("sts")
_bedrock = {"client": None, "expires": 0}

SCHEMA = """Amazon Redshift, schema olist (star schema of the Brazilian Olist marketplace, prices in BRL):
dim_customer(customer_key, customer_id, customer_unique_id, customer_city, customer_state, customer_zip_code_prefix, geography_key, data_source)
dim_seller(seller_key, seller_id, seller_city, seller_state, seller_zip_code_prefix, geography_key, data_source)
dim_product(product_key, product_id, category_pt, category_en, product_weight_g, product_photos_qty, data_source)
dim_geography(geography_key, state_code, state_name, region_name)
dim_payment_type(payment_type_key, payment_type)
dim_date(date_key INT yyyymmdd, full_date, cal_year, cal_quarter, cal_month, month_name, day_of_month, day_name, is_weekend)
fact_sales(order_id, order_item_id, customer_key, seller_key, product_key, purchase_date_key, delivered_date_key, estimated_date_key, order_status, price, freight_value, item_total, data_source)  -- one row per order item
fact_orders(order_id, customer_key, purchase_date_key, delivered_date_key, estimated_date_key, order_status, item_count, items_value, freight_total, payment_total, max_installments, avg_review, delivery_days, delay_days, is_late 0/1, data_source)  -- one row per order
fact_payments(order_id, payment_sequential, customer_key, payment_type_key, purchase_date_key, payment_installments, payment_value, data_source)  -- one row per payment
mv_monthly_sales(cal_year, cal_month, items_sold, revenue)
Joins: fact.*_key = dim.*_key ; fact.purchase_date_key = dim_date.date_key. Unknown members have key -1.
Revenue = SUM(fact_sales.price). Late % = AVG(fact_orders.is_late::float)."""

SQL_PROMPT = """You write ONE Amazon Redshift SQL query that answers the user's question.
Rules: only SELECT (or WITH ... SELECT); only tables in schema olist (write olist.<table>);
no comments; at most 50 result rows (use ORDER BY + LIMIT); give columns readable aliases.
If the question cannot be answered from these tables, reply exactly: CANNOT_ANSWER
Reply with the SQL only, no explanation.

{schema}"""

ANSWER_PROMPT = """You are a data analyst. Answer the question in 2-4 short sentences using ONLY the
query result below. Mention the key numbers. Prices are in Brazilian Real (R$).

Question: {question}
SQL used: {sql}
Result (columns, then rows): {result}"""

FORBIDDEN = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|grant|revoke|truncate|"
                       r"copy|unload|call|execute|vacuum|analyze|set|lock|comment)\b", re.I)


def bedrock():
    """A Bedrock client with temporary credentials from account B's role (renewed before expiry)."""
    if _bedrock["client"] is None or time.time() > _bedrock["expires"] - 300:
        creds = sts.assume_role(RoleArn=os.environ["BEDROCK_ROLE_ARN"],
                                RoleSessionName="olist-ask-data",
                                ExternalId=os.environ["EXTERNAL_ID"],
                                DurationSeconds=3600)["Credentials"]
        _bedrock["client"] = boto3.client(
            "bedrock-runtime", region_name=os.environ["BEDROCK_REGION"],
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"])
        _bedrock["expires"] = creds["Expiration"].timestamp()
    return _bedrock["client"]


def ask_model(system, user, max_tokens=600):
    r = bedrock().converse(
        modelId=os.environ["MODEL_ID"],
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
    )
    return "".join(part.get("text", "") for part in r["output"]["message"]["content"]).strip()


def safe_sql(text):
    """Return a runnable SELECT, or raise ValueError explaining why it was refused."""
    sql = re.sub(r"^```(?:sql)?|```$", "", text.strip(), flags=re.I | re.M).strip().rstrip(";").strip()
    if sql.upper() == "CANNOT_ANSWER":
        raise ValueError("This question cannot be answered from the Olist tables.")
    if ";" in sql:
        raise ValueError("Refused: more than one SQL statement.")
    if not re.match(r"^(select|with)\b", sql, re.I):
        raise ValueError("Refused: only SELECT queries are allowed.")
    if FORBIDDEN.search(sql):
        raise ValueError("Refused: the query contains a write or admin keyword.")
    if re.search(r"\b(pg_|stl_|stv_|svv_|sys_|information_schema)", sql, re.I):
        raise ValueError("Refused: system tables are not allowed.")
    # cap the result at 200 rows: change a bigger final LIMIT, or add one
    m = re.search(r"\blimit\s+(\d+)\s*$", sql, re.I)
    if m:
        return sql[:m.start(1)] + str(min(int(m.group(1)), 200))
    return f"{sql}\nLIMIT 200"


def run_sql(sql):
    sid = rsd.execute_statement(WorkgroupName=os.environ["WORKGROUP"], Database=os.environ["DATABASE"],
                                SecretArn=os.environ["SECRET_ARN"], Sql=sql)["Id"]
    deadline = time.time() + 40
    while True:
        d = rsd.describe_statement(Id=sid)
        if d["Status"] == "FINISHED":
            break
        if d["Status"] in ("FAILED", "ABORTED"):
            raise ValueError(f"Redshift could not run the query: {d.get('Error')}")
        if time.time() > deadline:
            raise TimeoutError("The query took too long.")
        time.sleep(0.5)
    if not d.get("HasResultSet"):
        return [], []
    res = rsd.get_statement_result(Id=sid)
    columns = [c["name"] for c in res["ColumnMetadata"]]
    rows = [[None if f.get("isNull") else next(iter(f.values())) for f in rec] for rec in res["Records"]]
    return columns, rows


def reply(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, default=str)}


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    body = json.loads(event["body"]) if isinstance(event.get("body"), str) else event
    question = str(body.get("question") or "").strip()[:500]
    if not question:
        return reply(400, {"error": "Please type a question."})

    sql = ""
    try:
        sql = safe_sql(ask_model(SQL_PROMPT.format(schema=SCHEMA), question))
        columns, rows = run_sql(sql)
        result = json.dumps({"columns": columns, "rows": rows[:50]}, default=str)[:6000]
        answer = ask_model("Answer briefly and only from the data given.",
                           ANSWER_PROMPT.format(question=question, sql=sql, result=result), 300)
        out = {"question": question, "sql": sql, "columns": columns, "rows": rows, "answer": answer}
        print(json.dumps({"question": question, "sql": sql, "rows": len(rows)}))
        return reply(200, out)
    except ValueError as e:  # refused or failed SQL: show the reason on the website
        return reply(422, {"question": question, "sql": sql, "error": str(e)})
    except Exception as e:
        print(f"ERROR {e}")
        return reply(500, {"question": question, "sql": sql, "error": str(e)})
