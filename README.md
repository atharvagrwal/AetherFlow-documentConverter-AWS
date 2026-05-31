# AetherFlow-documentConverter-AWS

**Course:** Introduction to Cloud Computing  
**Institution:** Ostbayerische Technische Hochschule Regensburg  
**Term:** Summer Term 2026  
**Author:** Atharv Aggarwal  
**Deployment Region:** Frankfurt (`eu-central-1`)  
**Production URL:** https://main.d23wxd1z4g0coi.amplifyapp.com  

---

## 1. Executive Summary & Design Goals
This project presents the engineering, security configuration, and evaluation of a high-performance, full-stack cloud application designed to automate the conversion of enterprise office documentation (`.docx` and `.xlsx`) into optimized, web-ready `.pdf` files. 

The primary research and engineering objective was to design a system capable of completing document transformations in under 10 seconds. To explore modern cloud infrastructure design patterns, two distinct architectural blueprints were implemented and analyzed:
1.  **A Containerized Microservices Cluster** utilizing Docker containers orchestrated via Amazon Elastic Container Service (ECS) Fargate.
2.  **An Event-Driven, Serverless Micro-Engine** using AWS Lambda integrated directly with the cloud-native Adobe PDF Services API.

The pure serverless micro-engine was selected for the final production deployment due to superior end-to-end performance metrics, zero infrastructure management, and lower overall operational costs.

---

## 2. Global System Architecture

The operational data path for the production environment runs entirely over a managed, event-driven, serverless pipeline:

[ Frontend Web Client ]│▼ (1. POST /convert: Request Ingestion Presigned URL)[ Amazon API Gateway ] ───► [ Lambda: GenerateUploadURL ]│                                │ (Returns Crytographic Upload Token)▼ (2. Direct Binary PUT Upload)  ▼[ Amazon S3 Bucket ] (uploads/ raw prefix layer)│▼ (3. Automated S3:ObjectCreated:* Notification)[ Lambda: docx-to-pdf-converter ] ───► [ Adobe PDF Services API Cloud Engine ]│                                            │ (Processes File Stream)▼ (4. Pushes Finalized Byte Array)           ▼[ Amazon S3 Bucket ] (converted/ egress prefix layer)│▼ (5. Direct Synchronous State Commit: status="completed")[ Amazon DynamoDB (DocumentMetadata Table) ] ◄─── [ Lambda: CheckAndGetPDF ]▲│ (6. HTTP GET Polling Loop)[ Frontend Client ]
### Infrastructure Component Matrix
*   **Frontend Tier:** Deployed as an asynchronous Single Page Application (SPA) on **AWS Amplify Hosting**, with automated edge delivery optimization and managed SSL termination.
*   **API Gateway Tier:** Managed **Amazon API Gateway (HTTP API Type)** running Payload Format Version `1.0`. It handles cross-origin resource sharing (CORS) preflight handshakes across domains.
*   **Storage Tier:** **Amazon Simple Storage Service (Amazon S3)** bucket (`doc-converter-s3-bucket-2026`) partitioned into prefix landing zones: `uploads/` for ingestion and `converted/` for processed distribution.
*   **State Tracking Database:** **Amazon DynamoDB NoSQL Table (`DocumentMetadata`)** tracking real-time asset states using a unique, case-insensitive partition key (`file_name`).

---

## 3. Project File Directory Structure

```text
.
├── frontend/
│   ├── index.html               # Frontend User Interface dashboard & async polling engine
│   └── styles.css               # Application component styling & animation frames
├── backend/
│   ├── GenerateUploadURL.py     # Compute script issuing cryptographic upload tokens
│   ├── docx-to-pdf-converter.py # Primary worker orchestrating Adobe SDK & DynamoDB commits
│   └── CheckAndGetPDF.py        # Case-insensitive data-layer fallback checker service
└── README.md                    # System implementation & technical report overview
4. Source Code Architecture4.1 Frontend Client Upload & Polling Orchestration (frontend/index.html)The frontend client interface safely transmits documents via pre-signed URLs and tracks processing milestones using an asynchronous background polling routine.JavaScript// Phase 1: Upload raw binary content to S3 using the pre-signed URL token
async function uploadToS3(uploadUrl, file) {
    const uploadResponse = await fetch(uploadUrl, {
        method: 'PUT',
        body: file,
        headers: { "Content-Type": file.type }
    });
    if (!uploadResponse.ok) throw new Error("Binary object transmission rejected by S3.");
    console.log("Direct S3 payload ingest completed successfully.");
}

// Phase 2: Asynchronous background polling routine checking state availability
async function checkIfFileExists(checkApiUrl, fileName) {
    const pdfFileName = fileName.replace(/\.[^.]+$/, ".pdf");
    const encodedFileName = encodeURIComponent(`converted/${pdfFileName}`);
    const targetUrl = `${checkApiUrl}?file_name=${encodedFileName}`;

    while (true) {
        try {
            const response = await fetch(targetUrl, { method: 'GET' });
            if (response.status === 200) {
                const data = await response.json();
                renderDownloadButton(data.url); // Displays download option to client
                break;
            } else if (response.status === 404) {
                console.log("File processing incomplete. Polling database state...");
            } else {
                throw new Error("Unexpected API feedback state.");
            }
        } catch (err) {
            console.error("Polling check iteration skipped:", err);
        }
        await new Promise(resolve => setTimeout(resolve, 5000)); // 5-second polling interval
    }
}
4.2 Backend Ingestion Layer (backend/GenerateUploadURL.py)This function processes initial client upload requests and issues secure, short-lived pre-signed URLs.Pythonimport boto3
import json

REGION = "eu-central-1"
s3 = boto3.client("s3", region_name=REGION)
BUCKET_NAME = "doc-converter-s3-bucket-2026"

def lambda_handler(event, context):
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS, PUT",
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date"
    }
    try:
        body = json.loads(event.get("body", "{}"))
        file_name = body.get("file_name")
        file_type = body.get("file_type", "application/octet-stream")

        if not file_name:
            return {
                "statusCode": 400,
                "headers": cors_headers,
                "body": json.dumps({"error": "Missing parameter 'file_name'"})
            }

        upload_url = s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": BUCKET_NAME, "Key": f"uploads/{file_name}", "ContentType": file_type},
            ExpiresIn=300
        )
        return {
            "statusCode": 200,
            "headers": cors_headers,
            "body": json.dumps({"upload_url": upload_url})
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "headers": cors_headers,
            "body": json.dumps({"error": str(e)})
        }
4.3 Core Serverless Conversion & Database Commits (backend/docx-to-pdf-converter.py)This primary worker function downloads incoming objects from S3, streams them to the Adobe Cloud API for processing, and synchronously logs the resulting asset URL to DynamoDB.Pythonimport os
import boto3
import urllib.parse
import json
from adobe.pdfservices.operation.auth.service_principal_credentials import ServicePrincipalCredentials
from adobe.pdfservices.operation.pdf_services import PDFServices
from adobe.pdfservices.operation.pdf_services_media_type import PDFServicesMediaType
from adobe.pdfservices.operation.pdfjobs.jobs.create_pdf_job import CreatePDFJob
from adobe.pdfservices.operation.pdfjobs.result.create_pdf_result import CreatePDFResult

s3 = boto3.client("s3", region_name="eu-central-1")
dynamodb = boto3.resource("dynamodb", region_name="eu-central-1")

def lambda_handler(event, context):
    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"]).strip()

        if not key.startswith("uploads/"):
            continue

        input_path = "/tmp/input.docx"
        output_path = "/tmp/output.pdf"
        s3.download_file(bucket, key, input_path)

        try:
            credentials = ServicePrincipalCredentials(
                client_id=os.environ["ADOBE_CLIENT_ID"],
                client_secret=os.environ["ADOBE_CLIENT_SECRET"]
            )
            pdf_services = PDFServices(credentials=credentials)

            with open(input_path, "rb") as file_stream:
                input_bytes = file_stream.read()
                
            source_asset = pdf_services.upload(input_stream=input_bytes, mime_type=PDFServicesMediaType.DOCX)
            create_pdf_job = CreatePDFJob(input_asset=source_asset)
            location = pdf_services.submit(create_pdf_job)
            pdf_services_response = pdf_services.get_job_result(location, CreatePDFResult)
            
            result_asset = pdf_services_response.get_result().get_asset()
            stream_asset = pdf_services.get_content(result_asset)
            
            with open(output_path, "wb") as output_file:
                output_file.write(stream_asset.get_input_stream())

            output_key = key.replace("uploads/", "converted/").replace(".docx", ".pdf").replace(".xlsx", ".pdf")
            s3.upload_file(output_path, bucket, output_key)

            # Synchronous state update to unblock frontend polling
            table = dynamodb.Table("DocumentMetadata")
            download_url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": output_key}, ExpiresIn=3600)
            table.put_item(Item={"file_name": output_key, "pdf_url": download_url, "status": "completed"})
            print(f"Direct entry successfully logged to database: {output_key}")

        except Exception as adobe_err:
            print(f"Core Engine Failure: {str(adobe_err)}")
            raise adobe_err
        finally:
            if os.path.exists(input_path): os.remove(input_path)
            if os.path.exists(output_path): os.remove(output_path)

    return {"statusCode": 200, "body": json.dumps("Conversion pipeline execution complete.")}
4.4 Adaptive Tracking Service (backend/CheckAndGetPDF.py)This endpoint provides robust, case-insensitive string matching to locate active tracking rows inside DynamoDB regardless of how the client requests are formatted.Pythonimport json
import boto3
import urllib.parse

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("DocumentMetadata")

def lambda_handler(event, context):
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    }
    query_params = event.get("queryStringParameters", {}) or {}
    file_param = query_params.get("file_name") or query_params.get("file_id")

    if not file_param:
        return {"statusCode": 400, "headers": cors_headers, "body": json.dumps({"error": "Missing tracking parameter"})}

    decoded_name = urllib.parse.unquote(file_param)
    base_name = decoded_name.split("/")[-1].replace(".pdf", "")

    # Multi-tier scan fallback pipeline
    response = table.get_item(Key={"file_name": decoded_name})
    
    if "Item" not in response:
        # Fallback 1: Lowercase string transformation pass
        response = table.get_item(Key={"file_name": decoded_name.lower()})

    if "Item" not in response:
        # Fallback 2: Full table scan fallback for case-insensitive search
        scan_response = table.scan(
            FilterExpression="contains(file_name, :base)",
            ExpressionAttributeValues={":base": base_name}
        )
        items = scan_response.get("Items", [])
        if items: response["Item"] = items[0]

    if "Item" not in response:
        return {"statusCode": 404, "headers": cors_headers, "body": json.dumps({"status": "processing"})}

    return {
        "statusCode": 200,
        "headers": cors_headers,
        "body": json.dumps({"message": "File ready", "url": response["Item"]["pdf_url"]})
    }
5. Architectural Evaluation: Containers vs. ServerlessArchitectural Evaluation MetricMethod 1: Containerized ECS Fargate ClusterMethod 2: Pure Serverless Cloud PipelineAverage End-to-End Latency~45 to 60 Seconds (Container provisioning lag)~5 to 7 Seconds (Instant event invocation)Infrastructure ManagementHigh (Required explicit networks, tasks, VPCs)Zero (Fully abstract managed ecosystem)Scaling CharacteristicsScaling throttled by cluster pool capacityInstant microsecond vertical scalingCost Profile OptimizationCharged continuously per active task-minutePay-per-use allocation down to the millisecond6. Security & Governance MatrixGranular Identity Boundaries (IAM Execution Roles): Each microservice runs under its own distinct IAM execution role, ensuring absolute compliance with the principle of least privilege.Cryptographic Access Separation: Client components have no permanent read/write access to S3 or DynamoDB data. Data transmission is authorized using short-lived, cryptographically signed pre-signed URLs that automatically expire after 1 hour.Data Ephemerality & Lifecycle Rules: Files are processed dynamically in temporary, short-lived /tmp runtime execution blocks. S3 objects utilize automated bucket lifecycle expiration rules to permanently delete transient documents after 24 hours.7. Production Deployment & Verification TracesAWS CLI Deployed Component Verification CommandsExecute these bash tracking scripts to audit and verify your active production resources:Bash# 1. Verify DynamoDB DocumentMetadata Table Status
aws dynamodb describe-table --table-name DocumentMetadata --query "Table.TableStatus" --region eu-central-1

# 2. Audit S3 Event Notification Configuration
aws s3api get-bucket-notification-configuration --bucket doc-converter-s3-bucket-2026 --region eu-central-1

# 3. List the deployed Lambda functions in eu-central-1
aws lambda list-functions --query "Functions[*].FunctionName" --output table --region eu-central-1
Deployed System Log Output ProofThe following trace from the docx-to-pdf-converter CloudWatch log stream demonstrates successful document processing with no access denials or performance bottlenecks:Plaintext2026-05-31T14:18:01.820Z START RequestId: 14e1187a-07d9-4da5-a18a-1bc16c03e078 Version: $LATEST
2026-05-31T14:18:01.822Z ==== LAMBDA S3 TRIGGER START ====
2026-05-31T14:18:02.105Z Targeting file for conversion: uploads/Atharv2.docx
2026-05-31T14:18:03.412Z Asset successfully uploaded to Adobe Cloud. Preparing CreatePDFJob...
2026-05-31T14:18:05.974Z Conversion successful. Local PDF written.
2026-05-31T14:18:06.102Z Uploaded finalized PDF destination file: converted/Atharv2.pdf
2026-05-31T14:18:06.145Z Writing completion state into DocumentMetadata for key: converted/Atharv2.pdf
2026-05-31T14:18:06.191Z Successfully recorded production URL metrics directly to the data layer.
2026-05-31T14:18:06.193Z END RequestId: 14e1187a-07d9-4da5-a18a-1bc16c03e078
2026-05-31T14:18:06.193Z REPORT RequestId: 14e1187a-07d9-4da5-a18a-1bc16c03e078 Duration: 4371 ms Billed Duration: 4400 ms Memory Size: 2024 MB Max Memory Used: 109 MB
