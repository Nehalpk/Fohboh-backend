import os
import json
import base64
from cryptography.fernet import Fernet
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.Random import get_random_bytes
import hashlib
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)


# Get encryption key from environment variable
#ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "your-default-key-change-this-in-production-32chars")
ENCRYPTION_KEY = "435435ldskfdslf;ds;fds;ds543"
def get_fernet_key():
    """Generate a Fernet key from the encryption key"""
    # Use the first 32 bytes of the SHA256 hash as the key
    key = hashlib.sha256(ENCRYPTION_KEY.encode()).digest()
    return base64.urlsafe_b64encode(key)

def encrypt_data_fernet(data: str) -> str:
    """Encrypt data using Fernet (symmetric encryption)"""
    try:
        key = get_fernet_key()
        fernet = Fernet(key)
        encrypted_data = fernet.encrypt(data.encode())
        return base64.b64encode(encrypted_data).decode()
    except Exception as e:
        logger.error(f"Encryption error: {str(e)}")
        raise HTTPException(status_code=500, detail="Encryption failed")

def decrypt_data_fernet(encrypted_data: str) -> str:
    """Decrypt data using Fernet"""
    try:
        key = get_fernet_key()
        fernet = Fernet(key)
        encrypted_bytes = base64.b64decode(encrypted_data.encode())
        decrypted_data = fernet.decrypt(encrypted_bytes)
        return decrypted_data.decode()
    except Exception as e:
        logger.error(f"Decryption error: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid encrypted data")

def encrypt_data_aes(data: str) -> str:
    """Encrypt data using AES (compatible with CryptoJS)"""
    try:
        # Convert key to 32 bytes
        key = hashlib.sha256(ENCRYPTION_KEY.encode()).digest()
        
        # Generate random IV
        iv = get_random_bytes(16)
        
        # Create cipher
        cipher = AES.new(key, AES.MODE_CBC, iv)
        
        # Pad and encrypt data
        padded_data = pad(data.encode(), AES.block_size)
        encrypted_data = cipher.encrypt(padded_data)
        
        # Combine IV and encrypted data
        result = iv + encrypted_data
        
        # Return base64 encoded result
        return base64.b64encode(result).decode()
    except Exception as e:
        logger.error(f"AES Encryption error: {str(e)}")
        raise HTTPException(status_code=500, detail="Encryption failed")

def decrypt_data_aes(encrypted_data: str) -> str:
    """Decrypt data using AES (compatible with CryptoJS)"""
    try:
        # Convert key to 32 bytes
        key = hashlib.sha256(ENCRYPTION_KEY.encode()).digest()
        
        # Decode base64
        encrypted_bytes = base64.b64decode(encrypted_data.encode())
        
        # Extract IV and encrypted data
        iv = encrypted_bytes[:16]
        encrypted_content = encrypted_bytes[16:]
        
        # Create cipher and decrypt
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted_padded = cipher.decrypt(encrypted_content)
        
        # Remove padding
        decrypted_data = unpad(decrypted_padded, AES.block_size)
        
        return decrypted_data.decode()
    except Exception as e:
        logger.error(f"AES Decryption error: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid encrypted data")

# Use AES for compatibility with frontend CryptoJS
encrypt_data = encrypt_data_aes
decrypt_data = decrypt_data_aes