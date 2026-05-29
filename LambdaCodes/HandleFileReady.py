import json
import boto3
import os

ecs = boto3.client("ecs")
dynamodb = boto3.resource("dynamodb")

table_name = os.environ.get("DYNAMODB_TABLE", "DocumentMetadata")
table = dynamodb.Table(table_name)

CLUSTER = os.environ.get("ECS_CLUSTER", "ConvertToPDFCluster")
TASK_DEFINITION = os.environ.get("TASK_DEFINITION", "ConvertToPDFTask")
SUBNET = os.environ.get("SUBNET", "")
SECURITY_GROUP = os.environ.get("SECURITY_GROUP", "")

def lambda_handler(event, context):
    try:
        for record in event["Records"]:
            bucket_name = record["s3"]["bucket"]["name"]
            file_key = record["s3"]["object"]["key"]

            if not file_key.startswith("uploads/"):
                print(f"Skipping non-upload file: {file_key}")
                continue

            file_name = file_key.split("/", 1)[1]

            table.put_item(
                Item={
                    "file_name": file_name,
                    "status": "processing",
                    "bucket": bucket_name,
                    "source_key": file_key
                }
            )

            response = ecs.run_task(
                cluster=CLUSTER,
                launchType="FARGATE",
                taskDefinition=TASK_DEFINITION,
                count=1,
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": [SUBNET],
                        "securityGroups": [SECURITY_GROUP],
                        "assignPublicIp": "ENABLED"
                    }
                }
            )

            print(response)

        return {
            "statusCode": 200,
            "body": json.dumps("ECS Task Triggered")
        }

    except Exception as e:
        print(f"Error processing event: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
