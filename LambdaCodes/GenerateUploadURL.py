import boto3
import json
import os

REGION = "eu-central-1"

# Initialize S3 client targeting the correct Frankfurt data infrastructure
s3 = boto3.client("s3", region_name=REGION)
BUCKET_NAME = "doc-converter-s3-bucket-2026"

def lambda_handler(event, context):
    # Setup consistent production-grade cross-origin resource response headers
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS, PUT",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date"
    }
    
    try:
        # Parse HTTP API request body safely
        body = json.loads(event.get("body", "{}"))

        file_name = body.get("file_name")
        file_type = body.get("file_type", "application/octet-stream")

        if not file_name:
            return {
                "statusCode": 400,
                "headers": cors_headers,
                "body": json.dumps({"error": "Missing file_name parameter"})
            }

        # Generate pre-signed URL for uploading the file safely to the landing area
        upload_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": BUCKET_NAME,
                "Key": f"uploads/{file_name}",
                "ContentType": file_type
            },
            ExpiresIn=300  # Upload URL expires in 5 minutes
        )

        # Generate pre-signed URL for downloading the converted PDF asset destination
        pdf_key = f"converted/{file_name}.pdf"
        download_url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": pdf_key},
            ExpiresIn=3600  # Download link expires in 1 hour
        )

        # Build structural mapping response payload
        return {
            "statusCode": 200,
            "headers": cors_headers,
            "body": json.dumps({
                "upload_url": upload_url,
                "pdf_url": download_url  
            })
        }

    except json.JSONDecodeError:
        return {
            "statusCode": 400,
            "headers": cors_headers,
            "body": json.dumps({"error": "Invalid JSON format in request body"})
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": cors_headers,
            "body": json.dumps({"error": str(e)})
        }
