# Provenance Guard

Provenance Guard is a production-ready, backend content classification API designed for creative sharing platforms (e.g., blogging portals, writing communities, music/art platforms). It evaluates whether submitted text is human-authored or AI-generated, provides confidence scoring, surfaces a user-facing transparency label, handles appeals, rate-limits submissions, and maintains a structured audit log.

---

## Architecture and Multi-Signal Detection

Provenance Guard uses a hybrid, multi-signal pipeline to make content classifications robust against bypasses and statistical noise. 

```
                                  +-------------------+
                                  |   POST /submit    |
                                  +-------------------+
                                            |
                                            v
                                  +-------------------+
                                  |   Rate Limiter    |
                                  +-------------------+
                                            |
                                            v
                                +-----------------------+
                                |  Detection Pipeline   |
                                +-----------------------+
                               /                         \
                              v                           v
                +--------------------------+  +--------------------------+
                |  Signal 1: Heuristics    |  |       Signal 2: LLM      |
                | - Sentence Var (SLV)     |  | - Forensic Linguistics   |
                | - Vocab Diversity (TTR)  |  | - predictability & flow  |
                +--------------------------+  +--------------------------+
                              \                           /
                               v                         v
                                +-----------------------+
                                |  Ensemble Aggregation |
                                |  (Weighted / Bias)    |
                                +-----------------------+
                                            |
                                            v
                                  +-------------------+
                                  | Label Assignment  |
                                  +-------------------+
                                 /                     \
                                v                       v
                      +-------------------+   +--------------------+
                      |    Audit Logs     |   |    API Response    |
                      | - SQLite DB       |   | - Classification   |
                      | - audit.jsonl     |   | - Confidence Score |
                      +-------------------+   | - Transparency Label|
                                              +--------------------+
```

### 1. Signal 1: Stylometric Heuristics (Structural Analysis)
* **Sentence Length Variance (SLV):** Measures the standard deviation of sentence word counts. Humans mix very short sentences with long, complex structures, producing a high variance. AI text generates statistically homogeneous word counts, leading to low variance.
* **Type-Token Ratio (TTR):** Measures vocabulary diversity (ratio of unique words to total words). Humans employ creative word choices and colloquialisms, leading to a high TTR. AI text maintains high-probability tokens and repetitive connector words, producing a lower TTR.
* **Punctuation Density:** Measures punctuation frequency. AI text uses highly conventional, evenly spaced punctuation, while human text exhibits irregular, stylistic variations.

### 2. Signal 2: Forensic Linguistic Analysis (LLM Analysis)
* Querying `llama-3.3-70b-versatile` (via Groq) to evaluate clichéd AI jargon (*delve, tapestry, testament, furthermore, critical, crucial*), standard five-paragraph rhetorical outlines, lack of personal narrative quirks, and overall readability.

---

## Transparency Labels (Verbatim Text)

We map classification confidence scores into plain-language, non-accusatory messages for readers:

| Classification | Confidence Range | Verbatim Label Text |
|---|---|---|
| **High-Confidence Human** | $0.00$ to $0.40$ | `"This work is classified as human-authored. Our analysis suggests a high probability of original human creation."` |
| **Uncertain** | $0.40$ to $0.80$ | `"This work has mixed stylistic markers. Our analysis is unable to determine the origin with high confidence, so the author's original attribution is displayed."` |
| **High-Confidence AI** | $0.80$ to $1.00$ | `"This work is flagged as AI-generated. Our analysis detected patterns highly consistent with artificial intelligence writing tools."` |

---

## Confidence Scoring & Ensemble Weighting

To prevent incorrect classifications of human content (false positives), we implement an **asymmetric calibration strategy**:
1. **Short Text Override:** If a text is shorter than 50 words, heuristics are mathematically unstable. The system overrides Heuristics and relies 100% on the LLM evaluation score.
2. **Long Text Weighted Ensemble:** For text $\ge 50$ words, the combined score is:
   $$\text{Combined Score} = 0.3 \times \text{Heuristics Score} + 0.7 \times \text{LLM Score}$$
3. **Threshold Guardrails:** Standard classifiers split at $0.5$. Provenance Guard uses an asymmetric layout where anything between $0.40$ and $0.80$ defaults to `Uncertain`, ensuring human text with slightly structured syntax is not falsely accused of being AI.

---

## Production Safety Infrastructure

### 1. Rate Limiting Configuration
We configure Flask-Limiter with limits mapped to typical usage on a creative platform:
* **`/submit` Endpoint:** `10 per minute` and `100 per day`. Humans do not publish complete literary works or long blog posts more than once every few minutes. This protects downstream Groq API allowances from script-based flooding.
* **`/appeal` Endpoint:** `5 per minute` and `50 per day`. Preventing malicious attempts to flood databases with update statements.

### 2. Appeals Workflow
When a creator receives a classification they believe is incorrect:
1. They POST an appeal specifying the `submission_id` and their context/reason.
2. The database updates the submission status to `"under_review"` and logs the creator's reason.
3. Once the status changes to `"under_review"`, public-facing UIs can substitute the classification label with a neutral "Under Review" badge, protecting the author's reputation during administrative audit.

---

## Structured Audit Logs

Provenance Guard stores audits in two parallel locations: a persistent SQLite database (`provenance_guard.db`) and an append-only JSON Lines file (`logs/audit.jsonl`).

### Sample Audit Log Entries (`logs/audit.jsonl`)

Here are three sample entries showing the JSON payload structure:

```json
{"timestamp": "2026-07-05T18:14:04.120531", "event": "submission", "submission_id": "sub_f42be70c", "author_id": "author_mary", "title": "Autumn Leaves", "content_preview": "The autumn leaves are falling on the ground.", "slv": 149.3, "ttr": 0.83, "punctuation_density": 0.03, "heuristic_score": 0.0, "llm_score": 0.1, "combined_score": 0.07, "classification": "human", "label_text": "This work is classified as human-authored. Our analysis suggests a high probability of original human creation.", "status": "active"}
{"timestamp": "2026-07-05T18:14:04.385012", "event": "submission", "submission_id": "sub_19c15084", "author_id": "author_mary", "title": "AI generated piece", "content_preview": "Delve into the tapestry of crucial multifaceted aspects.", "slv": 5.0, "ttr": 0.48, "punctuation_density": 0.02, "heuristic_score": 0.9, "llm_score": 0.95, "combined_score": 0.935, "classification": "ai", "label_text": "This work is flagged as AI-generated. Our analysis detected patterns highly consistent with artificial intelligence writing tools.", "status": "active"}
{"timestamp": "2026-07-05T18:14:04.559618", "event": "appeal", "submission_id": "sub_f42be70c", "author_id": "author_mary", "reason": "This was hand-written in my diary.", "previous_classification": "human"}
```

---

## Setup & Running

1. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Environment Configuration:**
   Create a `.env` file in the project root:
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   ```
3. **Start the API Server:**
   ```bash
   python app.py
   ```
   The Flask server runs on port `5001`.
