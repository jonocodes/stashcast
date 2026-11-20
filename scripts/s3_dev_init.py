#!/usr/bin/env python3
"""
Create the StashCast bucket on an S3-compatible server and make it publicly readable.

Podcast apps fetch enclosures without credentials, so objects need anonymous GetObject.
Listing the bucket is deliberately NOT allowed.

Used by docker-compose.minio.yml for local development. For Cloudflare R2, do the
equivalent in the dashboard instead: connect a custom domain to the bucket (R2 has no
bucket policies; public access is per-domain and does not allow listing).

Reads the same env vars as StashCast: STASHCAST_S3_BUCKET, STASHCAST_S3_ENDPOINT_URL,
STASHCAST_S3_REGION, STASHCAST_S3_ACCESS_KEY_ID, STASHCAST_S3_SECRET_ACCESS_KEY.
"""

import json
import os
import sys
import time

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError


def public_read_policy(bucket):
    return {
        'Version': '2012-10-17',
        'Statement': [
            {
                'Sid': 'PublicReadObjects',
                'Effect': 'Allow',
                'Principal': {'AWS': ['*']},
                'Action': ['s3:GetObject'],
                'Resource': [f'arn:aws:s3:::{bucket}/*'],
            }
        ],
    }


def main():
    bucket = os.environ['STASHCAST_S3_BUCKET']
    s3 = boto3.client(
        's3',
        endpoint_url=os.environ.get('STASHCAST_S3_ENDPOINT_URL') or None,
        region_name=os.environ.get('STASHCAST_S3_REGION') or 'us-east-1',
        aws_access_key_id=os.environ.get('STASHCAST_S3_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('STASHCAST_S3_SECRET_ACCESS_KEY'),
    )

    # Wait for the server to come up (compose starts services concurrently)
    for attempt in range(30):
        try:
            s3.list_buckets()
            break
        except (EndpointConnectionError, ClientError) as e:
            if attempt == 29:
                sys.exit(f'S3 endpoint not reachable: {e}')
            time.sleep(1)

    try:
        s3.create_bucket(Bucket=bucket)
        print(f'Created bucket {bucket}')
    except ClientError as e:
        if e.response['Error']['Code'] not in ('BucketAlreadyOwnedByYou', 'BucketAlreadyExists'):
            raise
        print(f'Bucket {bucket} already exists')

    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(public_read_policy(bucket)))
    print(f'Applied public-read (no listing) policy to {bucket}')


if __name__ == '__main__':
    main()
