# Provenance Guard Planning Document

## Architecture

Provenance Guard is structured as a Flask-based backend containing a multi-signal detection pipeline, a persistent SQLite database for audit trails and appeals, and a rate-limiting layer.

### System Diagram

```mermaid
graph TD
    User([Client / Creator]) -->|1. POST /submit| Server[Flask API Server]
    Server -->|2. Check Rate Limit| Limiter{Flask-Limiter}
    Limiter -->|Passed| Pipeline[Multi-Signal Detection Pipeline]
    Limiter -->|Failed| Res429[429 Too Many Requests]
    
    Pipeline -->|Signal 1: Local Calculations| Stylometrics[Stylometric Analyzer]
    Pipeline -->|Signal 2: Remote Prompting| Groq[Groq Llama-3.3-70b-versatile]
    
    Stylometrics -->|Heuristic Metrics| Ensemble[Ensemble Scoring Engine]
    Groq -->|LLM Verdict Score| Ensemble
    
    Ensemble -->|Weighted Calculation & Asymmetric Logic| Labeler[Label Assignment Engine]
    Labeler -->|Verdicts & Confidence| DB[(SQLite DB)]
    Labeler -->|Append Audit Entry| LogFile[(logs/audit.jsonl)]
    Labeler -->|Result Payload| Server
    Server -->|3. JSON Response| User
    
    User -->|4. POST /appeal| AppealRoute[Appeal Handler]
    AppealRoute -->|5. Update status to 'under_review' & log reason| DB
```

### Architecture Narrative
* **Submission Flow:** The client submits content to `POST /submit`. If the request passes the rate limiter, the pipeline calculates stylometric heuristics and queries Llama-3.3 via Groq. The engine aggregates the scores, maps them to a transparency label, stores the transaction in SQLite and the JSONL log, and returns the verdict.
* **Appeal Flow:** The client contests a decision via `POST /appeal`. The server updates the database status of that submission to `"under_review"` and appends the event to the JSONL log, ensuring subsequent lookups display a neutral status to protect the author.

---

## Detection Signals

### Signal 1: Stylometric Heuristics (Structural Analysis)
* **What it measures:** 
  1. **Sentence Length Variance (SLV):** The statistical variance ($\sigma^2$) of the word count per sentence.
  2. **Type-Token Ratio (TTR):** The ratio of unique words to total words.
  3. **Punctuation Density:** The count of punctuation marks relative to total text characters.
* **Output Format:** Numeric values for SLV, TTR, and Punctuation Density, combined into a normalized heuristic score between `0.0` (Highly Human) and `1.0` (Highly AI).
* **Why it differs between Human and AI:**
  * **SLV:** Humans write with high variance (some sentences are 3 words, some are 40). AI writing maintains a uniform pacing, meaning low variance.
  * **TTR:** Humans choose diverse, context-specific words, yielding a higher TTR. AI text leans on safe, highly probable tokens, resulting in lower vocabulary diversity.
* **Blind Spots:**
  * **Short Text (< 50 words):** Variance and TTR calculations become mathematically volatile.
  * **Prompt-Engineered AI:** A prompt instructing the AI to "write with irregular pacing and eccentric vocab" can trick these statistics.

### Signal 2: Forensic Linguistic Analysis (LLM Analysis)
* **What it measures:** Tonal coherence, clichéd transitions (*delve, tapestry, testament*), and structured patterns typical of modern AI models.
* **Output Format:** A JSON response containing `"ai_likelihood"` (a float between `0.0` and `1.0`) and `"reasoning"` (text explaining the linguistic details).
* **Why it differs between Human and AI:**
  * AI text is highly predictable due to probability distribution limits, while human writing features logical jumps, emotional nuances, and stylistic eccentricities.
* **Blind Spots:**
  * **Academic / Legal Writing:** Humans writing highly structured, formal papers can trigger the AI semantic detector.
  * **Non-Native English Texts:** Creators using simple, repetitive structures or machine translators can look like AI text.

---

## Uncertainty Representation & Score Calibration

* **What a score of 0.6 means:** 
  A combined score of `0.6` represents **Uncertainty**. It indicates that the text has conflicting signals (e.g., the LLM detected slight AI-like vocabulary, but the sentence structures were highly irregular and human-like). Rather than forcing a binary decision, the system maps this to the `Uncertain` classification, leaving the public label neutral.
* **Ensemble Weighting Formula:**
  * **Short Text (< 50 words):** Heuristics are ignored due to volatility.
    $$\text{Combined Score} = \text{LLM Score}$$
  * **Long Text ($\ge 50$ words):**
    $$\text{Combined Score} = 0.3 \times \text{Heuristic Score} + 0.7 \times \text{LLM Score}$$
* **Calibration Thresholds:**
  * **Likely Human:** $\text{score} < 0.40$
  * **Uncertain:** $0.40 \le \text{score} \le 0.80$
  * **Likely AI:** $\text{score} > 0.80$

---

## Transparency Label Design (Verbatim Texts)

* **High-Confidence Human:**
  > `"This work is classified as human-authored. Our analysis suggests a high probability of original human creation."`
* **Uncertain:**
  > `"This work has mixed stylistic markers. Our analysis is unable to determine the origin with high confidence, so the author's original attribution is displayed."`
* **High-Confidence AI:**
  > `"This work is flagged as AI-generated. Our analysis detected patterns highly consistent with artificial intelligence writing tools."`

---

## Appeals Workflow

* **Who can appeal:** Only the creator associated with the `author_id` of the original submission.
* **Information provided:** The original `submission_id` and a written text reasoning.
* **System Actions upon Receipt:**
  1. Validates the existence of the `submission_id`.
  2. Updates the SQL database record's `status` to `"under_review"` and saves the `appeal_reason`.
  3. Appends an `"appeal"` event record containing the reason to `logs/audit.jsonl`.
* **Human Reviewer Interface Queue:**
  A moderator querying the admin endpoint receives a structured JSON queue containing all submissions where `status = 'under_review'`. They can inspect:
  * The raw content and title.
  * The individual Signal 1 (SLV, TTR) and Signal 2 (LLM) scores.
  * The creator's appeal reason.

---

## Anticipated Edge Cases

1. **Repetitive Poetry (e.g., Villanelles or Ballads):**
   * *Description:* Human-written poems featuring refrains and highly structured lines (e.g., Edgar Allan Poe's "The Raven").
   * *Failure Mode:* The repeating phrases severely reduce the Type-Token Ratio (TTR) and sentence length variance, causing heuristics to flag the poem as AI.
   * *Mitigation:* The ensemble weights the LLM semantic signal higher, and the appeal status quickly neutralizes false classifications.
2. **Structured Software Code Explanations:**
   * *Description:* Technical documentation detailing code snippets in step-by-step guides.
   * *Failure Mode:* Explanations often use repetitive, dry, and structured verbs (e.g., "Implement the following function. Next, compile the code.").
   * *Mitigation:* The system uses the `Uncertain` buffer to prevent immediate flagging, allowing users to submit appeals.

---

## AI Tool Plan

### M3 (Submission Endpoint + Heuristics Signal)
* **Spec Sections Provided:** `Architecture` (diagram + narrative) + `Detection Signals` (Signal 1 Heuristics specifications).
* **AI Generation Request:** Generate the Flask application skeleton, configure routing, implement python-based functions for Sentence Length Variance, Type-Token Ratio, and Punctuation Density, and write local tests.
* **Verification Method:** Run unit tests against known inputs (e.g. texts of uniform length to assert SLV = 0) before integrating the second signal.

### M4 (Second Signal + Confidence Scoring)
* **Spec Sections Provided:** `Detection Signals` (Signal 2 LLM specifications) + `Uncertainty Representation & Score Calibration` + `Architecture` (system diagram).
* **AI Generation Request:** Integrate the Groq Llama-3.3-70b-versatile client with JSON mode. Implement the short-text override and the weighted ensemble scoring math.
* **Verification Method:** Compare scores of a known human-written blog post against an AI-generated essay, validating that the final combined scores fall into the expected ranges.

### M5 (Production Layer)
* **Spec Sections Provided:** `Transparency Label Design` + `Appeals Workflow` + `Architecture` (system diagram).
* **AI Generation Request:** Implement Flask-Limiter configurations, SQLite database status update query actions for `/appeal`, JSONL file appending, and custom Flask 429 error handlers.
* **Verification Method:** Loop sequential curl requests to trigger `429 Too Many Requests`. Run mock appeals to verify database status transitions to `"under_review"`.
