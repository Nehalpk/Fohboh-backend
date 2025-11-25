from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
import json
import uuid
from datetime import datetime
from src.chat_gpt import get_current_user, get_db, DB_CONFIG

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
VALID_CATEGORIES = ["Inventory", "Labor", "Sales"]

# Router
router = APIRouter(prefix="/notes", tags=["Notes Management"])

# Models
class FileEntry(BaseModel):
    name: str

class CategoryEntry(BaseModel):
    category: str
    files: List[FileEntry]

class CreateTextNoteRequest(BaseModel):
    categories: List[CategoryEntry]

class TextNoteResponse(BaseModel):
    id: str
    user_email: str
    categories: List[Dict[str, Any]]
    created_at: str

# Database Functions
def init_notes_table():
    """Initialize the database table for text notes if it doesn't exist"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Create table for text notes
        cur.execute("""
        CREATE TABLE IF NOT EXISTS text_notes (
            id VARCHAR(36) PRIMARY KEY,
            user_email VARCHAR(255) NOT NULL,
            content JSONB NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # Create index for faster queries by user_email
        cur.execute("""
        CREATE INDEX IF NOT EXISTS text_notes_user_email_idx 
        ON text_notes(user_email)
        """)
        
        conn.commit()
        logger.info("Text notes table initialized successfully")
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Error initializing text notes table: {str(e)}")
        raise
    finally:
        if conn:
            cur.close()
            conn.close()

def create_text_note(user_email: str, categories_data: List[Dict], conn) -> Dict:
    """
    Create a new text note with multiple categories and files.
    If a note already exists for this user, it replaces the existing note.
    
    Args:
        user_email: Email of the current user
        categories_data: List of category entries with files
        conn: Database connection
        
    Returns:
        Dict containing the created note information
    """
    try:
        cur = conn.cursor()
        
        # Validate each category
        for category_entry in categories_data:
            category = category_entry.get("category")
            if category not in VALID_CATEGORIES:
                raise ValueError(f"Invalid category: {category}. Must be one of: {', '.join(VALID_CATEGORIES)}")
                
            if not category_entry.get("files"):
                raise ValueError(f"Category '{category}' must have at least one file")
        
        # First, check if there's an existing note for this user
        cur.execute("""
            SELECT id FROM text_notes
            WHERE user_email = %s
            LIMIT 1
        """, (user_email,))
        
        existing_record = cur.fetchone()
        
        # Prepare JSON content
        content = {
            "categories": categories_data
        }
        
        if existing_record:
            # Update the existing record
            note_id = existing_record['id']
            cur.execute("""
                UPDATE text_notes 
                SET content = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                RETURNING id, user_email, content, created_at
            """, (json.dumps(content), note_id))
        else:
            # Generate a unique ID for new record
            note_id = str(uuid.uuid4())
            
            # Insert the new note
            cur.execute("""
                INSERT INTO text_notes (id, user_email, content)
                VALUES (%s, %s, %s)
                RETURNING id, user_email, content, created_at
            """, (note_id, user_email, json.dumps(content)))
        
        result = cur.fetchone()
        conn.commit()
        
        # Format response
        created_at = result["created_at"].isoformat() if result["created_at"] else None
        
        return {
            "id": result["id"],
            "user_email": result["user_email"],
            "categories": result["content"]["categories"],
            "created_at": created_at
        }
        
    except ValueError as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating text note: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error creating text note: {str(e)}")

def get_all_text_notes(user_email: str, conn) -> List[Dict]:
    """
    Get all text notes for a user
    
    Args:
        user_email: Email of the current user
        conn: Database connection
        
    Returns:
        List of text notes
    """
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, user_email, content, created_at
            FROM text_notes
            WHERE user_email = %s
            ORDER BY created_at DESC
        """, (user_email,))
        
        results = cur.fetchall()
        
        notes = []
        for result in results:
            created_at = result["created_at"].isoformat() if result["created_at"] else None
            
            notes.append({
                "id": result["id"],
                "user_email": result["user_email"],
                "categories": result["content"]["categories"],
                "created_at": created_at
            })
            
        return notes
        
    except Exception as e:
        logger.error(f"Error getting text notes: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting text notes: {str(e)}")

def get_text_note_by_id(note_id: str, user_email: str, conn) -> Dict:
    """
    Get a specific text note by ID
    
    Args:
        note_id: ID of the note to retrieve
        user_email: Email of the current user
        conn: Database connection
        
    Returns:
        Text note details
    """
    try:
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, user_email, content, created_at
            FROM text_notes
            WHERE id = %s AND user_email = %s
        """, (note_id, user_email))
        
        result = cur.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail=f"Text note with ID {note_id} not found")
            
        created_at = result["created_at"].isoformat() if result["created_at"] else None
        
        return {
            "id": result["id"],
            "user_email": result["user_email"],
            "categories": result["content"]["categories"],
            "created_at": created_at
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting text note: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error getting text note: {str(e)}")

def delete_text_note(note_id: str, user_email: str, conn) -> Dict:
    """
    Delete a text note
    
    Args:
        note_id: ID of the note to delete
        user_email: Email of the current user
        conn: Database connection
        
    Returns:
        Dictionary with delete confirmation
    """
    try:
        cur = conn.cursor()
        
        # Verify the note exists and belongs to this user
        cur.execute("""
            SELECT id 
            FROM text_notes
            WHERE id = %s AND user_email = %s
        """, (note_id, user_email))
        
        result = cur.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail=f"Text note with ID {note_id} not found")
            
        # Delete the note
        cur.execute("""
            DELETE FROM text_notes
            WHERE id = %s AND user_email = %s
            RETURNING id
        """, (note_id, user_email))
        
        deleted = cur.fetchone()
        conn.commit()
        
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Text note with ID {note_id} not found")
            
        return {
            "message": f"Text note with ID {note_id} deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting text note: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting text note: {str(e)}")

# API Routes
@router.post("/create", response_model=TextNoteResponse)
async def create_text_note_endpoint(
    request: CreateTextNoteRequest,
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Create a new text note with categories and files"""
    # Convert Pydantic models to dictionaries
    categories_data = []
    for category_entry in request.categories:
        files_data = [{"name": file.name} for file in category_entry.files]
        categories_data.append({
            "category": category_entry.category,
            "files": files_data
        })
    
    return create_text_note(current_user["email"], categories_data, conn)

@router.get("/current", response_model=TextNoteResponse)
async def get_current_text_note_endpoint(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Get the text note for the current user (only one per user)"""
    notes = get_all_text_notes(current_user["email"], conn)
    if not notes:
        raise HTTPException(status_code=404, detail="No text note found for current user")
    return notes[0]

@router.delete("/clear")
async def delete_current_text_note_endpoint(
    current_user: dict = Depends(get_current_user),
    conn = Depends(get_db)
):
    """Delete the current user's text note"""
    try:
        cur = conn.cursor()
        
        # Get the current user's note ID
        cur.execute("""
            SELECT id 
            FROM text_notes
            WHERE user_email = %s
            LIMIT 1
        """, (current_user["email"],))
        
        result = cur.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="No text note found for current user")
        
        note_id = result["id"]
        
        # Delete the note
        cur.execute("""
            DELETE FROM text_notes
            WHERE id = %s
            RETURNING id
        """, (note_id,))
        
        deleted = cur.fetchone()
        conn.commit()
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Failed to delete text note")
            
        return {
            "message": "Text note deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        logger.error(f"Error deleting text note: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error deleting text note: {str(e)}")


# Initialize the table when module is imported
init_notes_table()
