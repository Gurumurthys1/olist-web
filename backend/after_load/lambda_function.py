"""olist_after_load: last step of the olistcap_pipeline state machine, after LoadRedshift.

1. Marks website uploads as LOADED: every upload that was READY when this pipeline run
   started is now in Redshift (status READY -> LOADED in DynamoDB).
2. Starts a QuickSight SPICE refresh for each dataset, so QuickSight shows the new data
   without waiting for its daily schedule.
3. If uploads became READY while this run was going, starts one more run for them.

Input from Step Functions:  {"started.$": "$$.Execution.StartTime"}

Environment variables:
  TABLE          olist_uploads
  ACCOUNT_ID     517374107791
  DATASET_IDS    QuickSight dataset ids, comma separated (olist_sales_rs, olist_orders_rs)
                 leave empty to skip the QuickSight refresh
  PIPELINE_ARN   ARN of olistcap_pipeline (optional: empty = no follow-up run)
"""
import json
import os
import time

import boto3

DDB = boto3.resource("dynamodb").Table(os.environ["TABLE"])
qs = boto3.client("quicksight")
sfn = boto3.client("stepfunctions")


def mark_loaded(started):
    """READY uploads from before this run started -> LOADED."""
    started = (started or "")[:19]  # 2026-11-21T16:02:17.123Z -> 2026-11-21T16:02:17
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    items, kwargs = [], {}
    while True:
        page = DDB.scan(**kwargs)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]

    loaded, waiting = [], 0
    for item in items:
        ready_at = item.get("updated_at", item.get("created_at", ""))[:19]
        if item.get("status") == "READY" and started and ready_at > started:
            waiting += 1  # arrived during this run
        if item.get("status") == "READY" and (not started or ready_at <= started):
            DDB.update_item(
                Key={"upload_id": item["upload_id"]},
                UpdateExpression="SET #s = :s, #m = :m, loaded_at = :t, updated_at = :t",
                ConditionExpression="#s = :ready",  # skip if it changed meanwhile
                ExpressionAttributeNames={"#s": "status", "#m": "message"},
                ExpressionAttributeValues={":s": "LOADED", ":ready": "READY", ":t": now,
                                           ":m": "Loaded into Redshift"},
            )
            loaded.append(item["upload_id"])
    return loaded, waiting


def follow_up_run(waiting):
    """Uploads arrived while this run was going: start one more run for them.
    (This run is in its last step, so the new run starts once Redshift is loaded.)"""
    arn = os.environ.get("PIPELINE_ARN", "")
    if not waiting or not arn:
        return None
    name = f"followup-{int(time.time())}"
    try:
        sfn.start_execution(stateMachineArn=arn, name=name, input=json.dumps({"trigger": "follow-up"}))
        return name
    except Exception as e:
        print(f"could not start the follow-up run: {e}")
        return None


def refresh_spice():
    """One SPICE refresh per dataset. A failure here is reported, not fatal: the data is
    already in Redshift, and the daily QuickSight schedule will catch up."""
    account = os.environ.get("ACCOUNT_ID", "")
    results = {}
    for ds in [d.strip() for d in os.environ.get("DATASET_IDS", "").split(",") if d.strip()]:
        try:
            r = qs.create_ingestion(AwsAccountId=account, DataSetId=ds,
                                    IngestionId=f"pipeline-{int(time.time())}")
            results[ds] = r["IngestionStatus"]
        except Exception as e:
            print(f"SPICE refresh {ds} failed: {e}")
            results[ds] = f"failed: {str(e)[:200]}"
    return results


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    loaded, waiting = mark_loaded(event.get("started"))
    spice = refresh_spice()
    result = {"uploads_loaded": len(loaded), "upload_ids": loaded, "spice": spice,
              "uploads_waiting": waiting, "follow_up_run": follow_up_run(waiting)}
    print(result)
    return result
