#!/usr/bin/env python3

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import boto3
from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, scoped_session

load_dotenv()

# Add parent directory to Python path to import common modules
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from common.enums import Store, ReceiptStatus, TxStatus, PackageName
from common.models.receipt import Receipt
from common.models.product import Product
from common.utils.google import get_google_client
from common.utils.receipt import PlanetID
from common.utils.address import format_addr
from iap.utils import get_mileage, upsert_mileage

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Process Google IAP receipts that are missing from database")
    parser.add_argument("--order-id", required=True, help="Google order ID (e.g., GPA.3392-3387-9900-22421)")
    parser.add_argument("--agent-addr", required=True, help="Agent address")
    parser.add_argument("--avatar-addr", required=True, help="Avatar address")
    parser.add_argument("--purchase-token", required=True, help="Google purchase token")
    parser.add_argument("--sku", required=True, help="Google SKU (product ID)")
    parser.add_argument("--package-name", required=True, choices=['M', 'K'], 
                        help="Package name type: M for mobile, K for Korea mobile")
    parser.add_argument("--planet-id", required=True, 
                        help="Planet ID (e.g., odin, heimdall, thor)")
    parser.add_argument("--purchased-at", required=True,
                        help="Purchase date and time (e.g., 'Mar 4, 2025 11:38:29 AM UTC')")
    
    # Optional arguments with environment variable fallbacks
    parser.add_argument("--db-uri",  
                        default=os.environ.get("DATABASE_URL"),
                        help="Database URI (e.g., postgresql://user:password@host/database)")
    parser.add_argument("--google-credential", 
                        default=os.environ.get("GOOGLE_CREDENTIAL"),
                        help="Google Play Store API credentials (JSON format)")
    parser.add_argument("--sqs-url", 
                        default=os.environ.get("SQS_URL"),
                        help="SQS URL for sending messages to the worker")
    parser.add_argument("--region-name", 
                        default=os.environ.get("AWS_REGION", "us-east-2"), 
                        help="AWS region name (default: us-east-2)")
    parser.add_argument("--dry-run", action="store_true", 
                        help="Dry run mode, don't make actual changes")
    
    args = parser.parse_args()
    
    # Validate required parameters that might come from environment variables
    missing_params = []
    if not args.db_uri:
        missing_params.append("--db-uri or DB_URI environment variable")
    if not args.google_credential:
        missing_params.append("--google-credential or GOOGLE_CREDENTIAL environment variable")
    if not args.sqs_url:
        missing_params.append("--sqs-url or SQS_URL environment variable")
        
    if missing_params:
        parser.error(f"Missing required parameters: {', '.join(missing_params)}")
    
    return args

def parse_purchase_date(date_str):
    """Parse the purchase date string into a datetime object with UTC timezone"""
    try:
        # Handle various formats of date strings
        formats = [
            "%b %d, %Y %I:%M:%S %p %Z",  # Mar 4, 2025 11:38:29 AM UTC
            "%Y-%m-%d %H:%M:%S %Z",      # 2025-03-04 11:38:29 UTC
            "%Y-%m-%dT%H:%M:%S%z"        # 2025-03-04T11:38:29+0000
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                # If the format doesn't include timezone and the parsed time doesn't have timezone info
                if dt.tzinfo is None and "%Z" not in fmt and "%z" not in fmt:
                    # Assume UTC timezone
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
                
        raise ValueError(f"Could not parse date string: {date_str}")
    except Exception as e:
        print(f"Error parsing date: {e}")
        print("Using current UTC time as fallback")
        return datetime.now(timezone.utc)

def get_full_package_name(package_type):
    """Return the full package name based on the type (M or K)"""
    if package_type == 'M':
        return "com.planetariumlabs.ninechroniclesmobile"
    else:  # K
        return "com.planetariumlabs.ninechroniclesmobilek"

def validate_google_receipt(client, package_name, sku, token):
    """Validate a Google receipt with the Play Store"""
    try:
        resp = client.purchases().products().get(
            packageName=package_name, 
            productId=sku, 
            token=token
        ).execute()
        
        return resp
    except Exception as e:
        print(f"Error validating Google receipt: {e}")
        return None

def consume_purchase(client, package_name, sku, token, dry_run=False):
    """Consume a Google purchase to prevent auto-refund"""
    if dry_run:
        print(f"DRY RUN: Would consume purchase with SKU {sku} and token {token[:10]}...")
        return True
        
    try:
        result = client.purchases().products().consume(
            packageName=package_name, 
            productId=sku, 
            token=token
        ).execute()
        
        print(f"Consume purchase result: {result}")
        # Successful consumption should return an empty response
        return result == ""
    except Exception as e:
        print(f"Error consuming purchase: {e}")
        return False

def find_product_by_google_sku(session, google_sku):
    """Find a product in the database by Google SKU"""
    return session.scalar(select(Product).where(Product.google_sku == google_sku))

def find_receipt_by_order_id(session, order_id):
    """Find a receipt in the database by order ID"""
    return session.scalar(select(Receipt).where(Receipt.order_id == order_id))

def insert_receipt(session, receipt_data, dry_run=False):
    """Insert a new receipt record into the database"""
    receipt = Receipt(**receipt_data)
    
    if not dry_run:
        session.add(receipt)
        session.commit()
        session.refresh(receipt)
        print(f"Receipt inserted with ID: {receipt.id}, UUID: {receipt.uuid}")
    else:
        print("DRY RUN: Would insert receipt with data:")
        for key, value in receipt_data.items():
            print(f"  {key}: {value}")
    
    return receipt

def send_sqs_message(sqs_client, queue_url, message, dry_run=False):
    """Send a message to the SQS queue to trigger item delivery"""
    if not dry_run:
        response = sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message)
        )
        print(f"Message sent to SQS with ID: {response.get('MessageId')}")
        return response
    else:
        print("DRY RUN: Would send SQS message:")
        print(json.dumps(message, indent=2))
        return None

def main():
    args = parse_args()
    
    # Setup database connection
    engine = create_engine(args.db_uri)
    session = scoped_session(sessionmaker(bind=engine))
    
    # Setup Google client
    google_client = get_google_client(args.google_credential)
    
    # Setup SQS client
    sqs = boto3.client("sqs", region_name=args.region_name)
    
    # Determine full package name
    package_name = get_full_package_name(args.package_name)
    
    # Format addresses
    agent_addr = format_addr(args.agent_addr)
    avatar_addr = format_addr(args.avatar_addr)
    
    # Parse the purchased_at date
    purchased_at = parse_purchase_date(args.purchased_at)
    print(f"Using purchase date: {purchased_at.isoformat()} (UTC)")
    
    # Resolve planet ID
    try:
        planet_id = PlanetID[args.planet_id.upper()]
    except KeyError:
        print(f"Unknown planet ID: {args.planet_id}")
        planet_names = ", ".join([p.name for p in PlanetID])
        print(f"Available planet IDs: {planet_names}")
        return 1
    
    print(f"Looking for receipt with order ID: {args.order_id}")
    
    # Check if receipt already exists in database
    existing_receipt = find_receipt_by_order_id(session, args.order_id)
    
    if existing_receipt:
        print(f"Receipt already exists in database with ID: {existing_receipt.id}")
        print(f"Status: {existing_receipt.status.name}")
        
        if existing_receipt.status == ReceiptStatus.VALID:
            print("Receipt is valid. No further action needed.")
            return 0
        
        print(f"Receipt has status {existing_receipt.status.name}, might need manual investigation.")
        return 1
    
    # Receipt not found in database, verify with Google
    print("Receipt not found in database, verifying with Google Play Store...")
    receipt_data = validate_google_receipt(
        google_client, 
        package_name, 
        args.sku, 
        args.purchase_token
    )
    
    if not receipt_data:
        print("Failed to validate receipt with Google. Aborting.")
        return 1
    
    print(f"Google validation result: {json.dumps(receipt_data, indent=2)}")
    
    # Check if purchase is completed
    if receipt_data.get('purchaseState') != 0:  # 0 = PURCHASED
        print(f"Purchase state is not PURCHASED: {receipt_data.get('purchaseState')}")
        print("Receipt is not in a completed state. Aborting.")
        return 1
    
    # Check if order ID matches
    if receipt_data.get('orderId') != args.order_id:
        print(f"Order ID mismatch: expected {args.order_id}, got {receipt_data.get('orderId')}")
        print("Receipt order ID doesn't match. Aborting.")
        return 1
    
    # Consume the purchase to prevent auto-refund
    print("Consuming purchase to prevent auto-refund...")
    if not consume_purchase(google_client, package_name, args.sku, args.purchase_token, args.dry_run):
        print("Warning: Failed to consume purchase. Continuing anyway...")
    
    # Find product in database
    product = find_product_by_google_sku(session, args.sku)
    if not product:
        print(f"Product with Google SKU {args.sku} not found in database. Aborting.")
        return 1
    
    print(f"Found product: {product.name} (ID: {product.id})")
    
    # Create receipt data
    receipt_uuid = uuid.uuid4()
    
    # Get current mileage
    mileage_obj = get_mileage(session, agent_addr)
    current_mileage = mileage_obj.mileage
    
    # Calculate mileage change and result
    mileage_change = (product.mileage or 0) - (product.mileage_price or 0)
    mileage_result = current_mileage + mileage_change
    
    # Create receipt object
    new_receipt_data = {
        "store": Store.GOOGLE,
        "order_id": args.order_id,
        "uuid": receipt_uuid,
        "package_name": package_name,
        "data": {"Store": "GooglePlay", "Orderid": args.order_id, "PurchaseToken": args.purchase_token},
        "status": ReceiptStatus.VALID,
        "purchased_at": purchased_at,
        "product_id": product.id,
        "agent_addr": agent_addr,
        "avatar_addr": avatar_addr,
        "planet_id": planet_id.value,
        "mileage_change": mileage_change,
        "mileage_result": mileage_result,
        "msg": "Manual"
    }
    
    # Insert receipt
    new_receipt = insert_receipt(session, new_receipt_data, args.dry_run)
    
    # Update mileage
    if not args.dry_run:
        mileage_obj.mileage = mileage_result
        session.add(mileage_obj)
        session.commit()
        print(f"Mileage updated from {current_mileage} to {mileage_result}")
    else:
        print(f"DRY RUN: Would update mileage from {current_mileage} to {mileage_result}")
    
    # Send SQS message to trigger item delivery
    sqs_message = {
        "agent_addr": agent_addr,
        "avatar_addr": avatar_addr,
        "product_id": product.id,
        "uuid": str(receipt_uuid),
        "planet_id": args.planet_id,
        "package_name": package_name,
    }
    
    send_sqs_message(sqs, args.sqs_url, sqs_message, args.dry_run)
    
    print("Processing completed successfully.")
    return 0

if __name__ == "__main__":
    sys.exit(main()) 