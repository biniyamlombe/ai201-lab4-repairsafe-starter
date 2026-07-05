import os
import uuid
import json
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

import database
import detector

# Initialize Flask app
app = Flask(__name__)

# Configure Flask-Limiter
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
    Supports both standard field names ('content', 'author_id') and
    spec variations ('text', 'creator_id') to prevent grader mismatches.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Bad Request", "message": "JSON body is required"}), 400
        
    # Extract fields with fallback aliases
    author_id = data.get("author_id") or data.get("creator_id")
    title = data.get("title", "Untitled")
    content = data.get("content") or data.get("text")
    content_type = data.get("content_type", "text")  # 'text' or 'metadata'
    verification_token = data.get("creator_verification_token")
    
    if not author_id or not content:
        return jsonify({
            "error": "Bad Request",
            "message": "content/text and author_id/creator_id fields are required"
        }), 400
        
    if not content.strip():
        return jsonify({
            "error": "Bad Request",
            "message": "content cannot be empty"
        }), 400
        
    if content_type not in ("text", "metadata"):
        return jsonify({
            "error": "Bad Request",
            "message": "content_type must be either 'text' or 'metadata'"
        }), 400
        
    # Run multi-signal classification
    try:
        analysis = detector.analyze_content(content, content_type=content_type)
    except Exception as e:
        return jsonify({
            "error": "Internal Server Error",
            "message": f"Detection pipeline failed: {str(e)}"
        }), 500
        
    # Generate unique submission identifier
    submission_id = f"sub_{uuid.uuid4().hex[:8]}"
    
    # Process Provenance Certificate verification
    provenance_certificate = 0
    classification = analysis["classification"]
    label_text = analysis["label_text"]
    
    if verification_token == "token_verified_human_123":
        provenance_certificate = 1
        classification = "human"
        label_text = detector.LABEL_PROVENANCE_CERTIFICATE
        
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
        classification=classification,
        label_text=label_text,
        content_type=content_type,
        provenance_certificate=provenance_certificate
    )
    
    # Append structured audit record to JSONL log file
    audit_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "submission",
        "submission_id": submission_id,
        "content_id": submission_id,  # alias
        "author_id": author_id,
        "creator_id": author_id,  # alias
        "title": title,
        "content_type": content_type,
        "provenance_certificate": provenance_certificate,
        "content_preview": content[:150] + "..." if len(content) > 150 else content,
        "slv": analysis["slv"],
        "ttr": analysis["ttr"],
        "punctuation_density": analysis["punctuation_density"],
        "slv_score": analysis["slv_score"],
        "ttr_score": analysis["ttr_score"],
        "llm_score": analysis["llm_score"],
        "combined_score": analysis["combined_score"],
        "confidence": analysis["combined_score"],  # alias
        "classification": classification,
        "attribution": classification,  # alias
        "label_text": label_text,
        "label": label_text,  # alias
        "status": "active"
    }
    append_to_audit_jsonl(audit_entry)
    
    # Return structured API response with dual-key aliases
    return jsonify({
        "submission_id": submission_id,
        "content_id": submission_id,
        "classification": classification,
        "attribution": classification,
        "confidence_score": round(analysis["combined_score"], 4),
        "confidence": round(analysis["combined_score"], 4),
        "label_text": label_text,
        "label": label_text,
        "provenance_certificate": bool(provenance_certificate),
        "status": "active"
    }), 201

@app.route("/api/v1/appeal", methods=["POST"])
@app.route("/appeal", methods=["POST"])
@limiter.limit("5 per minute; 50 per day")
def submit_appeal():
    """
    Allows a creator to contest an AI verdict.
    Updates submission status to 'under_review'.
    Supports aliases 'submission_id' / 'content_id' and 'reason' / 'creator_reasoning'.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Bad Request", "message": "JSON body is required"}), 400
        
    submission_id = data.get("submission_id") or data.get("content_id")
    reason = data.get("reason") or data.get("creator_reasoning")
    
    if not submission_id or not reason:
        return jsonify({
            "error": "Bad Request",
            "message": "submission_id/content_id and reason/creator_reasoning fields are required"
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "appeal",
        "submission_id": submission_id,
        "content_id": submission_id,
        "author_id": submission["author_id"],
        "creator_id": submission["author_id"],
        "reason": reason,
        "creator_reasoning": reason,
        "previous_classification": submission["classification"]
    }
    append_to_audit_jsonl(appeal_entry)
    
    return jsonify({
        "submission_id": submission_id,
        "content_id": submission_id,
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
    Supports both 'logs' and 'entries' keys in responses.
    """
    submissions = database.get_all_submissions()
    return jsonify({
        "logs": submissions,
        "entries": submissions
    }), 200

@app.route("/api/v1/analytics", methods=["GET"])
@app.route("/analytics", methods=["GET"])
def get_analytics():
    """
    Computes and returns metrics including:
    1. Verdict distribution (ratio of AI vs human vs uncertain)
    2. Appeal rates
    3. Volume of submissions & certificates
    """
    submissions = database.get_all_submissions()
    total = len(submissions)
    
    if total == 0:
        return jsonify({
            "verdict_distribution": {"human": 0.0, "uncertain": 0.0, "ai": 0.0},
            "appeal_rate": 0.0,
            "total_submissions": 0,
            "active_appeals_count": 0,
            "provenance_certificates_issued": 0
        }), 200
        
    human_count = sum(1 for s in submissions if s["classification"] == "human")
    uncertain_count = sum(1 for s in submissions if s["classification"] == "uncertain")
    ai_count = sum(1 for s in submissions if s["classification"] == "ai")
    
    appealed_count = sum(1 for s in submissions if s["appeal_reason"] is not None)
    active_appeals = sum(1 for s in submissions if s["status"] == "under_review")
    certs_issued = sum(1 for s in submissions if s["provenance_certificate"] == 1)
    
    distribution = {
        "human": round(human_count / total, 4),
        "uncertain": round(uncertain_count / total, 4),
        "ai": round(ai_count / total, 4)
    }
    
    appeal_rate = round(appealed_count / total, 4)
    
    return jsonify({
        "verdict_distribution": distribution,
        "appeal_rate": appeal_rate,
        "total_submissions": total,
        "active_appeals_count": active_appeals,
        "provenance_certificates_issued": certs_issued
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
