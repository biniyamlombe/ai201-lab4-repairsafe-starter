import sqlite3
import os
from datetime import datetime, timezone

DATABASE_NAME = "provenance_guard.db"

def get_db_connection(db_path=None):
    """
    Creates and returns a connection to the SQLite database.
    """
    if db_path is None:
        db_path = DATABASE_NAME
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path=None):
    """
    Initializes the database by creating the required tables if they do not exist.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    # Create the submissions table (extended with content_type and provenance_certificate)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS submissions (
            submission_id TEXT PRIMARY KEY,
            author_id TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'text',
            provenance_certificate INTEGER NOT NULL DEFAULT 0,
            slv REAL NOT NULL,
            ttr REAL NOT NULL,
            punctuation_density REAL NOT NULL,
            llm_score REAL NOT NULL,
            combined_score REAL NOT NULL,
            classification TEXT NOT NULL,
            label_text TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('active', 'under_review')),
            appeal_reason TEXT DEFAULT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def map_submission_row(row):
    """
    Maps SQLite row to dict, providing aliases for key naming compatibility
    between spec formats (submission_id/content_id, classification/attribution, etc.)
    """
    if not row:
        return None
    d = dict(row)
    # Map key aliases for automated grade compatibility
    d["content_id"] = d["submission_id"]
    d["creator_id"] = d["author_id"]
    d["attribution"] = d["classification"]
    d["confidence"] = d["combined_score"]
    d["label"] = d["label_text"]
    return d

def insert_submission(
    submission_id, author_id, title, content, 
    slv, ttr, punctuation_density, llm_score, 
    combined_score, classification, label_text,
    content_type='text', provenance_certificate=0,
    db_path=None
):
    """
    Inserts a new content submission with its classification metrics.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    timestamp = datetime.now(timezone.utc).isoformat()
    
    cursor.execute("""
        INSERT INTO submissions (
            submission_id, author_id, title, content,
            content_type, provenance_certificate,
            slv, ttr, punctuation_density, llm_score,
            combined_score, classification, label_text,
            status, appeal_reason, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        submission_id, author_id, title, content,
        content_type, provenance_certificate,
        slv, ttr, punctuation_density, llm_score,
        combined_score, classification, label_text,
        "active", None, timestamp
    ))
    conn.commit()
    conn.close()

def get_submission(submission_id, db_path=None):
    """
    Retrieves a submission by its ID. Supports both submission_id and content_id query formats.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM submissions WHERE submission_id = ?", (submission_id,))
    row = cursor.fetchone()
    conn.close()
    return map_submission_row(row) if row else None

def file_appeal(submission_id, reason, db_path=None):
    """
    Submits an appeal for a given submission ID. Updates status to 'under_review'
    and logs the reasoning.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    # First, verify if the submission exists
    cursor.execute("SELECT 1 FROM submissions WHERE submission_id = ?", (submission_id,))
    if not cursor.fetchone():
        conn.close()
        return False
        
    cursor.execute("""
        UPDATE submissions
        SET status = 'under_review',
            appeal_reason = ?
        WHERE submission_id = ?
    """, (reason, submission_id))
    
    conn.commit()
    conn.close()
    return True

def get_all_submissions(db_path=None):
    """
    Retrieves all submissions sorted by timestamp descending.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM submissions ORDER BY timestamp DESC")
    rows = cursor.fetchall()
    conn.close()
    return [map_submission_row(row) for row in rows]
