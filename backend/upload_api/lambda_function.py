"""olist_upload_api: the website's upload endpoints (behind the Cognito JWT authorizer).

  POST /uploads   {"filename": "my_orders.csv"}   admin only
      -> creates a record in DynamoDB (status WAITING_FILE)
      -> returns a presigned S3 URL; the browser PUTs the CSV straight to
         s3://<BUCKET>/raw/uploads_incoming/<upload_id>.csv  (valid 5 minutes)
  GET  /uploads   -> the 20 most recent uploads with their status (any logged-in user)

The CSV is then checked by the olist_upload_validator Lambda (S3 trigger).

Environment variables:
  BUCKET   olistcap-data-2026
  TABLE    olist_uploads
"""
import json
import os
import re
import secrets
import time

import boto3
from botocore.config import Config

BUCKET = os.environ["BUCKET"]
TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE"])
s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-east-1"),
                  config=Config(signature_version="s3v4"))


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
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", str(body.get("filename") or "upload.csv"))[:80]
    if not filename.lower().endswith(".csv"):
        return reply(400, {"error": "Only .csv files can be uploaded."})

    upload_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)
    key = f"raw/uploads_incoming/{upload_id}.csv"
    TABLE.put_item(Item={
        "upload_id": upload_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_email": claims.get("email", ""),
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
        page = TABLE.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    items.sort(key=lambda i: i.get("created_at", ""), reverse=True)
    return reply(200, {"uploads": items[:20]})


def lambda_handler(event, context):
    route = event.get("routeKey", "")
    try:
        if route == "POST /uploads":
            return create_upload(event)
        if route == "GET /uploads":
            return list_uploads()
        return reply(404, {"error": f"unknown route {route}"})
    except Exception as e:  # shown on the website and in CloudWatch logs
        print(f"ERROR {e}")
        return reply(500, {"error": str(e)})
