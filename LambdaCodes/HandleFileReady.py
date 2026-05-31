import json
import boto3
import os
import urllib.parse

s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

table = dynamodb.Table(os.environ["DYNAMODB_TABLE"])

def lambda_handler(event, context):
    print("==== HANDLE FILE READY TRIGGER START ====")
    print("S3 Event payload received:", json.dumps(event))

    try:
        for record in event.get("Records", []):
            bucket = record["s3"]["bucket"]["name"]
            raw_key = record["s3"]["object"]["key"]
            
            # Unquote the key safely to parse spaces/special characters
            key = urllib.parse.unquote_plus(raw_key)
            print(f"Processing database entry mapping for localized asset key: {key}")

            if not key.lower().startswith("converted/") or not key.lower().endswith(".pdf"):
                print(f"Skipping key execution path outside conversion rules: {key}")
                continue

            # Generate long-lasting pre-signed URL for the frontend application link
            presigned_url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=3600  # 1 hour expiration window
            )

            # Isolate base filename (e.g., "ATHagg")
            base_filename = key.split("/")[-1].replace(".pdf", "")
            print(f"Isolated tracking base target: {base_filename}")

            # -----------------------------------------------------------------
            # CASE-INSENSITIVE DYNAMODB SYNC ENGINE
            # -----------------------------------------------------------------
            # 1. Write the primary record matching the exact S3 physical case
            print(f"Writing primary frontend lookup row into DynamoDB for: {key}")
            table.put_item(
                Item={
                    "file_name": key,
                    "pdf_url": presigned_url,
                    "status": "completed",
                    "base_name": base_filename
                }
            )

            # 2. To avoid case mismatches with frontend requests, write a duplicate row 
            # with standard casing variations if needed
            variations = [key, key.lower(), f"converted/{base_filename.lower()}.pdf"]
            for var_key in set(variations):
                table.put_item(
                    Item={
                        "file_name": var_key,
                        "pdf_url": presigned_url,
                        "status": "completed"
                    }
                )

            # 3. Clean up any stale initial processing rows (handling casing variants)
            for ext in [".docx", ".xlsx", ".DOCX", ".XLSX"]:
                for base_variant in [base_filename, base_filename.lower(), base_filename.upper()]:
                    transient_key = f"{base_variant}{ext}"
                    try:
                        table.delete_item(Key={"file_name": transient_key})
                        print(f"Cleaned up transient processing marker: {transient_key}")
                    except Exception as e:
                        pass
            # -----------------------------------------------------------------

            # Clean up raw source assets from S3 uploads landing zone
            for ext in [".docx", ".xlsx", ".DOCX", ".XLSX"]:
                for base_variant in [base_filename, base_filename.lower(), base_filename.upper()]:
                    target_upload_key = f"uploads/{base_variant}{ext}"
                    try:
                        s3.delete_object(Bucket=bucket, Key=target_upload_key)
                        print(f"Cleaned up source file from landing zone: {target_upload_key}")
                    except Exception:
                        pass

        return {
            "statusCode": 200, 
            "body": json.dumps("Database records synced and case alignment validated.")
        }

    except Exception as e:
        print("Critical Execution Pipeline Error:", str(e))
        return {
            "statusCode": 500, 
            "body": json.dumps(f"HandleFileReady execution trace failed: {str(e)}")
        }
