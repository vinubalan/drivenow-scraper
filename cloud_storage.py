"""
Cloud storage module for uploading screenshots to Cloudflare R2.
"""
import os
import boto3
from botocore.exceptions import ClientError
from typing import Optional
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class CloudflareR2Storage:
    """Handles file uploads to Cloudflare R2 storage."""
    
    def __init__(self):
        """
        Initialize Cloudflare R2 storage client.
        """
        # Get R2 credentials from environment variables
        self.account_id = os.getenv('CLOUDFLARE_ACCOUNT_ID')
        self.access_key_id = os.getenv('CLOUDFLARE_R2_ACCESS_KEY_ID')
        self.secret_access_key = os.getenv('CLOUDFLARE_R2_SECRET_ACCESS_KEY')
        self.bucket_name = os.getenv('CLOUDFLARE_R2_BUCKET_NAME')
        self.public_url = os.getenv('CLOUDFLARE_R2_PUBLIC_URL')  # Optional: public URL for accessing files
        
        if not all([self.account_id, self.access_key_id, self.secret_access_key, self.bucket_name]):
            raise ValueError(
                "Missing Cloudflare R2 credentials. "
                "Please set CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_R2_ACCESS_KEY_ID, "
                "CLOUDFLARE_R2_SECRET_ACCESS_KEY, and CLOUDFLARE_R2_BUCKET_NAME in .env"
            )
        
        # Initialize S3 client for R2 (R2 is S3-compatible)
        self.s3_client = boto3.client(
            's3',
            endpoint_url=f'https://{self.account_id}.r2.cloudflarestorage.com',
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name='auto'  # R2 doesn't use regions
        )
    
    def upload_file(self, local_file_path: str, remote_file_path: str, 
                   content_type: str = 'image/jpeg') -> Optional[str]:
        """
        Upload a file to Cloudflare R2.
        
        Args:
            local_file_path: Path to local file to upload
            remote_file_path: Path/name for file in R2 bucket
            content_type: MIME type of the file
            
        Returns:
            Public URL of uploaded file if public_url is configured, otherwise None
        """
        try:
            # Upload file to R2
            self.s3_client.upload_file(
                local_file_path,
                self.bucket_name,
                remote_file_path,
                ExtraArgs={
                    'ContentType': content_type
                }
            )
            
            logger.info(f"Uploaded {local_file_path} to R2 as {remote_file_path}")
            
            # Return public URL if configured, otherwise return R2 path for reference
            if self.public_url:
                # Remove leading slash from remote_file_path if present
                remote_path = remote_file_path.lstrip('/')
                return f"{self.public_url.rstrip('/')}/{remote_path}"
            
            # If no public URL, return the R2 path (user can construct URL themselves)
            # Format: r2://bucket-name/path or just the path
            return f"r2://{self.bucket_name}/{remote_file_path.lstrip('/')}"
        except ClientError as e:
            logger.error(f"Failed to upload {local_file_path} to R2: {str(e)}")
            raise Exception(f"R2 upload failed: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error uploading to R2: {str(e)}")
            raise
    
    def delete_file(self, remote_file_path: str) -> bool:
        """
        Delete a file from Cloudflare R2.
        
        Args:
            remote_file_path: Path/name of file in R2 bucket
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.s3_client.delete_object(
                Bucket=self.bucket_name,
                Key=remote_file_path
            )
            logger.info(f"Deleted {remote_file_path} from R2")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete {remote_file_path} from R2: {str(e)}")
            return False
    
    def file_exists(self, remote_file_path: str) -> bool:
        """
        Check if a file exists in Cloudflare R2.
        
        Args:
            remote_file_path: Path/name of file in R2 bucket
            
        Returns:
            True if file exists, False otherwise
        """
        try:
            self.s3_client.head_object(
                Bucket=self.bucket_name,
                Key=remote_file_path
            )
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise

