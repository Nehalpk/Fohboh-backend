from fastapi import UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import boto3
import uuid
import os
import time
from typing import Optional, List
import logging
import requests
import json
from fastapi.responses import Response
# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Audio Configuration
BUCKET_NAME = "my-audio-demo"
UPLOAD_BASE_DIR = "uploads/users"

# Initialize AWS clients
s3_client = boto3.client(
    's3',
    region_name='us-east-1',
    aws_access_key_id='AKIA6G75DKGISWQMC7CR',
    aws_secret_access_key='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'
)

transcribe_client = boto3.client(
    'transcribe',
    region_name='us-east-1',
    aws_access_key_id='AKIA6G75DKGISWQMC7CR',
    aws_secret_access_key='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'
)

def get_user_folder_path(user_id: int, email: str, role: str) -> str:
    """Create and return user-specific folder path"""
    safe_email = email.replace('@', '_at_')
    folder_name = f"{user_id}_{safe_email}_{role}"
    user_folder = os.path.join(UPLOAD_BASE_DIR, folder_name, "audio")
    os.makedirs(user_folder, exist_ok=True)
    return user_folder
#-------------------------------------------------
async def download_file(file_type: str, filename: str, current_user: dict):
    """Download audio or transcript file"""
    try:
        user_folder = get_user_folder_path(
            current_user["id"], 
            current_user["email"], 
            current_user["role"]
        )
        
        file_key = f"{user_folder}/{filename}"
        
        try:
            # Get the file from S3
            response = s3_client.get_object(
                Bucket=BUCKET_NAME,
                Key=file_key
            )
            
            # Get the file content
            file_content = response['Body'].read()
            
            # Determine content type
            content_type = 'application/json' if file_type == 'transcript' else 'audio/wav'
            
            # Return FileResponse for direct download
            return Response(
                content=file_content,
                media_type=content_type,
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"'
                }
            )
            
        except s3_client.exceptions.NoSuchKey:
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {filename}"
            )
            
    except Exception as e:
        logger.error(f"Error downloading file: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error downloading file: {str(e)}"
        )
#--------------------------------------------------


async def process_audio_upload(file: UploadFile, current_user: dict):
    """Process and transcribe audio file for a specific user"""
    user_folder = get_user_folder_path(
        current_user["id"], 
        current_user["email"], 
        current_user["role"]
    )
    local_path = None
    
    try:
        # Validate file type
        if not file.filename.lower().endswith(('.wav', '.mp3', '.m4a')):
            raise HTTPException(
                status_code=400,
                detail="File must be an audio file (WAV, MP3, or M4A)"
            )
        
        # Generate unique filename while preserving extension
        file_extension = os.path.splitext(file.filename)[1]
        filename = f"{uuid.uuid4()}{file_extension}"
        s3_key = f"{user_folder}/{filename}"
        local_path = os.path.join(user_folder, filename)
        
        logger.info(f"Saving uploaded file to {local_path}")
        
        # Create user directory if it doesn't exist
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        # Save uploaded file
        with open(local_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        if not os.path.exists(local_path):
            raise Exception("Failed to save uploaded file")

        logger.info("Uploading to S3...")
        # Upload to S3
        s3_client.upload_file(
            local_path,
            BUCKET_NAME,
            s3_key
        )
        logger.info("Upload completed")

        # Generate S3 URI for transcription
        s3_uri = f"s3://{BUCKET_NAME}/{s3_key}"
        
        logger.info("Starting transcription job...")
        # Start transcription job
        job_name = f"transcription_{uuid.uuid4().hex[:8]}"
        
        # Determine media format for transcription
        media_format = file_extension.lower().replace('.', '')
        if media_format == 'm4a':
            media_format = 'mp4'  # AWS Transcribe uses 'mp4' for M4A files
            
        transcribe_client.start_transcription_job(
            TranscriptionJobName=job_name,
            Media={'MediaFileUri': s3_uri},
            MediaFormat=media_format,
            LanguageCode='en-US'
        )

        logger.info("Waiting for transcription to complete...")
        while True:
            status = transcribe_client.get_transcription_job(TranscriptionJobName=job_name)
            current_status = status['TranscriptionJob']['TranscriptionJobStatus']
            logger.info(f"Transcription status: {current_status}")
            
            if current_status in ['COMPLETED', 'FAILED']:
                break
            time.sleep(5)

        if status['TranscriptionJob']['TranscriptionJobStatus'] == 'COMPLETED':
            transcript_uri = status['TranscriptionJob']['Transcript']['TranscriptFileUri']
            logger.info("Transcription completed successfully")
            
            # Download transcript JSON
            try:
                transcript_response = requests.get(transcript_uri)
                transcript_data = transcript_response.json()
                
                # Generate transcript filename
                transcript_filename = f"{os.path.splitext(filename)[0]}.json"
                transcript_key = f"{user_folder}/{transcript_filename}"
                
                # Save transcript to S3
                s3_client.put_object(
                    Bucket=BUCKET_NAME,
                    Key=transcript_key,
                    Body=json.dumps(transcript_data, indent=2),
                    ContentType='application/json'
                )
                
                s3_transcript_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{transcript_key}"
                
                return {
                    "message": "Audio uploaded and transcribed successfully",
                    "audio_url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}",
                    "transcript_url": s3_transcript_url,
                    "filename": filename,
                    "transcript_filename": transcript_filename
                }
            except Exception as e:
                logger.error(f"Error saving transcript: {str(e)}")
                # Return response without local transcript if saving fails
                return {
                    "message": "Audio uploaded and transcribed successfully (transcript save failed)",
                    "audio_url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{s3_key}",
                    "transcript_url": transcript_uri,
                    "filename": filename
                }
        else:
            raise Exception("Transcription job failed")

    except Exception as e:
        logger.error(f"Error occurred: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"An error occurred: {str(e)}"
        )
    finally:
        # Clean up temporary file
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
                logger.info(f"Cleaned up temporary file: {local_path}")
            except Exception as e:
                logger.error(f"Error cleaning up file: {str(e)}")

async def list_user_audios(current_user: dict) -> List[dict]:
    """List all audio files for a specific user from S3"""
    try:
        user_folder = get_user_folder_path(
            current_user["id"], 
            current_user["email"], 
            current_user["role"]
        )
        
        # List objects in the user's folder
        response = s3_client.list_objects_v2(
            Bucket=BUCKET_NAME,
            Prefix=f"{user_folder}/"
        )
        
        audios = []
        if 'Contents' in response:
            for obj in response['Contents']:
                # Skip folder itself or json files
                if obj['Key'].endswith('/') or obj['Key'].endswith('.json'):
                    continue
                    
                # Get file info
                file_key = obj['Key']
                filename = os.path.basename(file_key)
                
                # Skip empty files
                if obj['Size'] == 0:
                    continue
                
                # Get transcription job if exists
                try:
                    job_name = f"transcription_{os.path.splitext(filename)[0]}"
                    trans_response = transcribe_client.get_transcription_job(
                        TranscriptionJobName=job_name
                    )
                    if trans_response['TranscriptionJob']['TranscriptionJobStatus'] == 'COMPLETED':
                        transcript_uri = trans_response['TranscriptionJob']['Transcript']['TranscriptFileUri']
                    else:
                        transcript_uri = None
                except:
                    transcript_uri = None
                
                # Generate transcript filename and check if it exists in S3
                base_name = os.path.splitext(filename)[0]
                transcript_filename = f"{base_name}.json"
                transcript_key = f"{user_folder}/{transcript_filename}"
                
                # Check if transcript exists in S3
                try:
                    s3_client.head_object(Bucket=BUCKET_NAME, Key=transcript_key)
                    transcript_exists = True
                    local_transcript_url = f"https://{BUCKET_NAME}.s3.amazonaws.com/{transcript_key}"
                except:
                    transcript_exists = False
                    local_transcript_url = None
                
                audios.append({
                    "filename": filename,
                    "upload_date": obj['LastModified'].strftime("%Y-%m-%d %H:%M:%S"),
                    "size": obj['Size'],
                    "audio_url": f"https://{BUCKET_NAME}.s3.amazonaws.com/{file_key}",
                    "transcript_url": local_transcript_url if transcript_exists else transcript_uri,
                    "transcript_filename": transcript_filename if transcript_exists else None
                })
        
        # Sort by upload date, newest first
        audios.sort(key=lambda x: x['upload_date'], reverse=True)
        return audios
        
    except Exception as e:
        logger.error(f"Error listing user audios: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving audio files: {str(e)}"
        )