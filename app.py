import os
import uuid
import json
from datetime import datetime
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import database
import detector

# Initialize Flask app
app = Flask(__name__)

# Configure Flask-Limiter
# Limits are based on typical usage for a writing platform:
# - Creators write/publish text in sessions, so 10 submissions per minute / 100 per day is reasonable.
# - Appeals are even rarer, limiting to 5 per minute / 50 per day prevents database write flooding.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# Ensure folders exist
os.makedirs("logs", exist_ok=True)
LOG_FILE_PATH = "logs/audit.jsonl"

# Initialize database
database.init_db()

@app.errorhandler(429)
def rate_limit_handler(e):
    """
    Custom error handler for rate limit violations. Returns a structured JSON response.
    """
    return jsonify({
        "error": "Too Many Requests",
        "message": "You have exceeded your rate limit. Please try again later.",
        "limit": str(e.description)
    }), 429

def append_to_audit_jsonl(entry):
    """
    Helper to append structured records to the audit.jsonl log file.
    """
    with open(LOG_FILE_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")

@app.route("/api/v1/submit", methods=["POST"])
@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute; 100 per day")
def submit_content():
    """
    Accepts text content for analysis. Returns the attribution result,
    confidence score, and user-facing transparency label text.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Bad Request", "message": "JSON body is required"}), 400
        
    author_id = data.get("author_id")
    title = data.get("title")
    content = data.get("content")
    
    if not author_id or not title or not content:
        return jsonify({
            "error": "Bad Request",
            "message": "author_id, title, and content fields are required"
        }), 400
        
    if not content.strip():
        return jsonify({
            "error": "Bad Request",
            "message": "content cannot be empty"
        }), 400
        
    # Run multi-signal classification
    try:
        analysis = detector.analyze_content(content)
    except Exception as e:
        return jsonify({
            "error": "Internal Server Error",
            "message": f"Detection pipeline failed: {str(e)}"
        }), 500
        
    # Generate unique submission identifier
    submission_id = f"sub_{uuid.uuid4().hex[:8]}"
    
    # Store verdict in SQLite database
    database.insert_submission(
        submission_id=submission_id,
        author_id=author_id,
        title=title,
        content=content,
        slv=analysis["slv"],
        ttr=analysis["ttr"],
        punctuation_density=analysis["punctuation_density"],
        llm_score=analysis["llm_score"],
        combined_score=analysis["combined_score"],
        classification=analysis["classification"],
        label_text=analysis["label_text"]
    )
    
    # Append structured audit record to JSONL log file
    audit_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": "submission",
        "submission_id": submission_id,
        "author_id": author_id,
        "title": title,
        "content_preview": content[:150] + "..." if len(content) > 150 else content,
        "slv": analysis["slv"],
        "ttr": analysis["ttr"],
        "punctuation_density": analysis["punctuation_density"],
        "heuristic_score": analysis["heuristic_score"],
        "llm_score": analysis["llm_score"],
        "combined_score": analysis["combined_score"],
        "classification": analysis["classification"],
        "label_text": analysis["label_text"],
        "status": "active"
    }
    append_to_audit_jsonl(audit_entry)
    
    # Return structured API response
    return jsonify({
        "submission_id": submission_id,
        "classification": analysis["classification"],
        "confidence_score": round(analysis["combined_score"], 4),
        "label_text": analysis["label_text"],
        "status": "active"
    }), 201

@app.route("/api/v1/appeal", methods=["POST"])
@app.route("/appeal", methods=["POST"])
@limiter.limit("5 per minute; 50 per day")
def submit_appeal():
    """
    Allows a creator to contest an AI verdict.
    Updates submission status to 'under_review'.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Bad Request", "message": "JSON body is required"}), 400
        
    submission_id = data.get("submission_id")
    reason = data.get("reason")
    
    if not submission_id or not reason:
        return jsonify({
            "error": "Bad Request",
            "message": "submission_id and reason fields are required"
        }), 400
        
    if not reason.strip():
        return jsonify({
            "error": "Bad Request",
            "message": "reason cannot be empty"
        }), 400
        
    # Get current state from database to verify existence
    submission = database.get_submission(submission_id)
    if not submission:
        return jsonify({"error": "Not Found", "message": f"Submission {submission_id} does not exist"}), 404
        
    # Update status to under review
    success = database.file_appeal(submission_id, reason)
    if not success:
         return jsonify({"error": "Internal Error", "message": "Failed to update submission status"}), 500
         
    # Log the appeal event in JSONL
    appeal_entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "event": "appeal",
        "submission_id": submission_id,
        "author_id": submission["author_id"],
        "reason": reason,
        "previous_classification": submission["classification"]
    }
    append_to_audit_jsonl(appeal_entry)
    
    return jsonify({
        "submission_id": submission_id,
        "status": "under_review",
        "message": "Appeal successfully logged. Content is now under review."
    }), 200

@app.route("/api/v1/logs", methods=["GET"])
@app.route("/api/v1/log", methods=["GET"])
@app.route("/logs", methods=["GET"])
@app.route("/log", methods=["GET"])
def get_logs():
    """
    Returns all logged decisions from the SQLite database.
    """
    submissions = database.get_all_submissions()
    return jsonify({"logs": submissions}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
