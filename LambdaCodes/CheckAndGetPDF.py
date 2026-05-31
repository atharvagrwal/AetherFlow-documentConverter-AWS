import json
import boto3
import os
import urllib.parse

dynamodb = boto3.resource("dynamodb")
table_name = os.environ.get("DYNAMODB_TABLE", "DocumentMetadata")
table = dynamodb.Table(table_name)

def lambda_handler(event, context):
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date"
    }
    
    try:
        query_params = event.get("queryStringParameters", {})
        if not query_params:
            return {
                "statusCode": 400,
                "headers": cors_headers,
                "body": json.dumps({"error": "Missing query parameters"})
            }

        # Extract whatever the frontend sends (handles both 'file_name' or 'file_id')
        file_param = query_params.get("file_name") or query_params.get("file_id")
        
        if not file_param:
            return {
                "statusCode": 400,
                "headers": cors_headers,
                "body": json.dumps({"error": "Missing file identifier parameter"})
            }

        # Decode the file parameter string safely
        decoded_name = urllib.parse.unquote(file_param)
        print(f"Frontend requested asset lookup for: {decoded_name}")

        # Extract raw base name to run a case-insensitive backup scan if needed
        base_name = decoded_name.split("/")[-1].replace(".pdf", "")

        # 1. Try an exact match check first
        response = table.get_item(Key={"file_name": decoded_name})
        
        # 2. Check variation matches (lowercase, uppercase, etc.)
        if "Item" not in response:
            variations = [decoded_name.lower(), decoded_name.upper(), f"converted/{base_name}.pdf", f"converted/{base_name.lower()}.pdf"]
            for var in variations:
                alt_response = table.get_item(Key={"file_name": var})
                if "Item" in alt_response:
                    response = alt_response
                    break

        # 3. If still not found, do a fallback scan to find the item by status
        if "Item" not in response:
            print("Exact match not found. Running defensive fallback table scan...")
            scan_response = table.scan(
                FilterExpression="contains(file_name, :base)",
                ExpressionAttributeValues={":base": base_name}
            )
            items = scan_response.get("Items", [])
            if items:
                # Grab the first matching completed item
                response["Item"] = items[0]

        # If the item is truly not ready or processed yet
        if "Item" not in response:
            return {
                "statusCode": 404,
                "headers": cors_headers,
                "body": json.dumps({"status": "processing", "message": "Pipeline processing your document..."})
            }

        # Extract target download values securely
        item = response["Item"]
        pdf_url = item.get("pdf_url")

        return {
            "statusCode": 200,
            "headers": cors_headers,
            "body": json.dumps({
                "message": "PDF URL found", 
                "url": pdf_url
            })
        }

    except Exception as e:
        print(f"Critical execution crash: {str(e)}")
        return {
            "statusCode": 500,
            "headers": cors_headers,
            "body": json.dumps({"error": str(e)})
        }
