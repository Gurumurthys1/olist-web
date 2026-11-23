"""olist_upload_api: the website's upload endpoints (behind the Cognito JWT authorizer).

  POST /uploads   {"table": "orders", "filename": "my_orders.csv"}   admin only
      -> creates a record in DynamoDB (status WAITING_FILE)
      -> returns a presigned S3 URL; the browser PUTs the CSV straight to
         s3://<BUCKET>/raw/uploads_incoming/<table>/<upload_id>.csv  (valid 5 minutes)
  GET  /uploads                 -> the 20 most recent uploads with their status,
                                   plus the latest pipeline run (if PIPELINE_ARN is set)
  GET  /preview?table=orders    -> rows to show above the upload form:
         "uploaded": the latest rows added from the website for that table
         "sample":   the first rows of the original Olist file in raw/<table>/
  POST /process                 -> "Process now": starts the olistcap_pipeline state machine
                                   (admin only; refused while a run is still going)

The CSV is then checked by the upload validator Lambda (S3 trigger).

Environment variables:
  BUCKET        olistcap-data-2026
  TABLE         olist_uploads
  PIPELINE_ARN  ARN of the olistcap_pipeline state machine (optional until Phase 5)
"""
import csv
import io
import json
import os
import re
import secrets
import time

import boto3
from botocore.config import Config

BUCKET = os.environ["BUCKET"]
DDB = boto3.resource("dynamodb").Table(os.environ["TABLE"])
s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                  config=Config(signature_version="s3v4"))

PIPELINE_ARN = os.environ.get("PIPELINE_ARN", "")
sfn = boto3.client("stepfunctions")

TABLES = ["orders", "order_items", "payments", "reviews", "customers", "sellers", "products",
          "category_translation", "geolocation"]
PREVIEW_ROWS = 10


def reply(status, body):
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, default=str)}


def claims_of(event):
    return (event.get("requestContext", {}).get("authorizer", {})
            .get("jwt", {}).get("claims", {}))


def create_upload(event):
    claims = claims_of(event)
    if "admin" not in str(claims.get("cognito:groups", "")):
        return reply(403, {"error": "Only users in the admin group can upload data."})

    body = json.loads(event.get("body") or "{}")
    table = body.get("table")
    if table not in TABLES:
        return reply(400, {"error": f"table must be one of {', '.join(TABLES)}"})
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", str(body.get("filename") or "upload.csv"))[:80]
    if not filename.lower().endswith(".csv"):
        return reply(400, {"error": "Only .csv files can be uploaded."})

    upload_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)
    key = f"raw/uploads_incoming/{table}/{upload_id}.csv"
    DDB.put_item(Item={
        "upload_id": upload_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_email": claims.get("email", ""),
        "table_name": table,
        "filename": filename,
        "s3_key": key,
        "status": "WAITING_FILE",
        "message": "Waiting for the file to arrive in S3",
    })
    url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET, "Key": key, "ContentType": "text/csv"},
        ExpiresIn=300,
    )
    return reply(200, {"upload_id": upload_id, "url": url})


def list_uploads():
    items, kwargs = [], {}
    while True:  # small table: a full scan is fine
        page = DDB.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    ready = sum(1 for i in items if i.get("status") == "READY")
    return reply(200, {"uploads": items[:20], "ready_count": ready, "pipeline": last_run()})


def last_run():
    """The newest pipeline run: status, start, stop. None if the pipeline is not configured."""
    if not PIPELINE_ARN:
        return None
    runs = sfn.list_executions(stateMachineArn=PIPELINE_ARN, maxResults=1)["executions"]
    if not runs:
        return {"status": "NEVER_RUN"}
    r = runs[0]
    return {"name": r["name"], "status": r["status"],
            "started": r["startDate"].isoformat(),
            "stopped": r["stopDate"].isoformat() if r.get("stopDate") else None}


def process_now(event):
    claims = claims_of(event)
    if "admin" not in str(claims.get("cognito:groups", "")):
        return reply(403, {"error": "Only users in the admin group can start the pipeline."})
    if not PIPELINE_ARN:
        return reply(400, {"error": "PIPELINE_ARN is not set on the upload API Lambda."})
    running = sfn.list_executions(stateMachineArn=PIPELINE_ARN, statusFilter="RUNNING",
                                  maxResults=1)["executions"]
    if running:
        return reply(409, {"error": "The pipeline is already running. Wait for it to finish."})
    name = "web-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)
    sfn.start_execution(stateMachineArn=PIPELINE_ARN, name=name,
                        input=json.dumps({"trigger": "website", "by": claims.get("email", "")}))
    return reply(200, {"started": name})


def sample_rows(table):
    """First rows of the original Olist CSV. Only the first 64 KB is downloaded."""
    objs = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"raw/{table}/").get("Contents", [])
    files = [o["Key"] for o in objs if o["Key"].endswith(".csv")]
    if not files:
        return [], []
    head = s3.get_object(Bucket=BUCKET, Key=files[0], Range="bytes=0-65535")["Body"].read()
    text = head.decode("utf-8-sig", "replace")
    text = text[: text.rfind("\n")]  # drop the last, probably cut, line
    reader = csv.DictReader(io.StringIO(text))
    columns = [c.strip().strip('"') for c in (reader.fieldnames or [])]
    reader.fieldnames = columns
    rows = []
    for row in reader:
        rows.append(row)
        if len(rows) == PREVIEW_ROWS:
            break
    return columns, rows


def uploaded_rows(table):
    """Latest rows added from the website (newest upload first)."""
    objs = s3.list_objects_v2(Bucket=BUCKET, Prefix=f"raw/upload_{table}/").get("Contents", [])
    rows = []
    for obj in sorted(objs, key=lambda o: o["LastModified"], reverse=True):
        body = s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read().decode("utf-8")
        rows += [json.loads(line) for line in body.splitlines() if line.strip()][::-1]
        if len(rows) >= PREVIEW_ROWS:
            break
    return rows[:PREVIEW_ROWS]


def preview(event):
    table = (event.get("queryStringParameters") or {}).get("table")
    if table not in TABLES:
        return reply(400, {"error": f"table must be one of {', '.join(TABLES)}"})
    columns, sample = sample_rows(table)
    return reply(200, {"table": table, "columns": columns, "sample": sample,
                       "uploaded": uploaded_rows(table)})


def lambda_handler(event, context):
    route = event.get("routeKey", "")
    try:
        if route == "POST /uploads":
            return create_upload(event)
        if route == "GET /uploads":
            return list_uploads()
        if route == "GET /preview":
            return preview(event)
        if route == "POST /process":
            return process_now(event)
        return reply(404, {"error": f"unknown route {route}"})
    except Exception as e:  # shown on the website and in CloudWatch logs
        print(f"ERROR {e}")
        return reply(500, {"error": str(e)})
