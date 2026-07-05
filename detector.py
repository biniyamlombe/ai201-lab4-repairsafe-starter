import re
import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

# Define the user-facing transparency label texts verbatim
LABEL_HIGH_HUMAN = "This work is classified as human-authored. Our analysis suggests a high probability of original human creation."
LABEL_HIGH_AI = "This work is flagged as AI-generated. Our analysis detected patterns highly consistent with artificial intelligence writing tools."
LABEL_UNCERTAIN = "This work has mixed stylistic markers. Our analysis is unable to determine the origin with high confidence, so the author's original attribution is displayed."
LABEL_PROVENANCE_CERTIFICATE = "Verified Human Creator Certificate: This content has been verified as original human writing by a certified author."

def split_sentences(text):
    """
    Split text into sentences using simple punctuation boundaries.
    Handles basic punctuation (.!?).
    """
    sentences = re.split(r'[.!?]+(?:\s+|$)', text)
    return [s.strip() for s in sentences if s.strip()]

def get_words(text):
    """
    Extracts lowercase words from text, stripping punctuation.
    """
    cleaned = re.sub(r'[^\w\s]', '', text.lower())
    return cleaned.split()

def calculate_slv(text):
    """
    Calculates Sentence Length Variance (SLV).
    High variance is typical of humans; low variance is typical of AI.
    """
    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    lengths = [len(get_words(s)) for s in sentences]
    if len(lengths) < 2:
        return 0.0
    mean = sum(lengths) / len(lengths)
    variance = sum((x - mean) ** 2 for x in lengths) / (len(lengths) - 1)
    return variance

def calculate_ttr(text):
    """
    Calculates Type-Token Ratio (TTR) representing vocabulary diversity.
    """
    words = get_words(text)
    if not words:
        return 0.0
    unique_words = set(words)
    return len(unique_words) / len(words)

def calculate_punctuation_density(text):
    """
    Calculates punctuation frequency relative to text length.
    """
    if not text:
        return 0.0
    punctuation_chars = set('.,!?;:"\'()[]{}--')
    punc_count = sum(1 for char in text if char in punctuation_chars)
    return punc_count / len(text)

def get_slv_score(slv):
    """
    Normalizes Sentence Length Variance to a 0.0-1.0 AI probability score.
    Variance > 25 is human (0.0 score); variance < 4 is AI (1.0 score).
    """
    clamped_slv = max(4.0, min(25.0, slv))
    return 1.0 - ((clamped_slv - 4.0) / (25.0 - 4.0))

def get_ttr_score(ttr):
    """
    Normalizes Type-Token Ratio to a 0.0-1.0 AI probability score.
    TTR > 0.65 is human (0.0 score); TTR < 0.45 is AI (1.0 score).
    """
    clamped_ttr = max(0.45, min(0.65, ttr))
    return 1.0 - ((clamped_ttr - 0.45) / (0.65 - 0.45))

def get_llm_score(text, content_type='text'):
    """
    Calls Groq Llama-3.3-70b-versatile to evaluate text semantic patterns.
    Uses custom prompt configurations based on content_type (Multi-Modal).
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set.")
        
    client = Groq(api_key=api_key)
    
    text_prompt = (
        "You are an expert forensic linguist specializing in distinguishing human-written text from AI-generated text.\n"
        "Analyze the submitted text for:\n"
        "1. Vocabulary choices (e.g., overuse of words like 'delve', 'tapestry', 'testament', 'furthermore').\n"
        "2. Rhetorical structures (e.g., predictable introductory summaries, extremely balanced paragraph formatting, repetitive transition styles).\n"
        "3. Sentence rhythm and flow (e.g., lack of stylistic eccentricity, flat emotional resonance).\n\n"
        "You must return a JSON object with this exact structure:\n"
        "{\n"
        "  \"ai_likelihood\": <float between 0.0 and 1.0 representing the probability that the text is AI-generated>,\n"
        "  \"reasoning\": \"<brief 1-2 sentence explanation of your linguistic findings>\"\n"
        "}\n"
        "Do not write anything else. Return ONLY valid JSON."
    )
    
    metadata_prompt = (
        "You are an expert forensic linguist specializing in distinguishing human-written image descriptions (alt text) from AI-generated descriptions.\n"
        "Analyze the submitted description for:\n"
        "1. AI clichés (e.g., starting with 'A beautiful photo of...', 'In this image, we see...', 'This image depicts...').\n"
        "2. Overly descriptive, listing multiple elements rather than selecting the human-like focal points of the scene.\n"
        "3. Flat, highly structured syntactic structures.\n\n"
        "You must return a JSON object with this exact structure:\n"
        "{\n"
        "  \"ai_likelihood\": <float between 0.0 and 1.0 representing the probability that the text is AI-generated>,\n"
        "  \"reasoning\": \"<brief 1-2 sentence explanation of your linguistic findings>\"\n"
        "}\n"
        "Do not write anything else. Return ONLY valid JSON."
    )
    
    system_prompt = metadata_prompt if content_type == 'metadata' else text_prompt
    
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        response_format={"type": "json_object"},
        temperature=0.0
    )
    
    try:
        result = json.loads(response.choices[0].message.content)
        ai_likelihood = float(result.get("ai_likelihood", 0.5))
        return max(0.0, min(1.0, ai_likelihood))
    except Exception as e:
        print(f"Error parsing LLM response: {e}. Raw content: {response.choices[0].message.content}")
        return 0.5  # Fallback to neutral if LLM fails

def analyze_content(text, content_type='text'):
    """
    Orchestrates the multi-signal detection pipeline (Ensemble Detection).
    Signals:
    1. SLV score (Sentence variance structure)
    2. TTR score (Vocabulary diversity)
    3. Groq LLM score (Forensics semantic engine)
    """
    words = get_words(text)
    word_count = len(words)
    
    # Calculate Signal 1 & 2: Local Metrics
    slv = calculate_slv(text)
    ttr = calculate_ttr(text)
    punc_density = calculate_punctuation_density(text)
    
    slv_score = get_slv_score(slv)
    ttr_score = get_ttr_score(ttr)
    
    # Calculate Signal 3: LLM Forensics
    try:
        llm_score = get_llm_score(text, content_type=content_type)
    except Exception as e:
        print(f"LLM signal failed: {e}. Falling back to heuristic-only scoring.")
        llm_score = 0.5 * slv_score + 0.5 * ttr_score
        
    # Ensemble combination math
    # Short text bypass: if word count < 50, metrics are too volatile, use LLM only
    if word_count < 50:
        combined_score = llm_score
    else:
        # Long text weighted voting strategy
        # 15% SLV + 15% TTR + 70% LLM
        combined_score = 0.15 * slv_score + 0.15 * ttr_score + 0.70 * llm_score
        
    # Categorization based on asymmetric thresholds
    if combined_score > 0.80:
        classification = "ai"
        label_text = LABEL_HIGH_AI
    elif combined_score < 0.40:
        classification = "human"
        label_text = LABEL_HIGH_HUMAN
    else:
        classification = "uncertain"
        label_text = LABEL_UNCERTAIN
        
    return {
        "slv": slv,
        "ttr": ttr,
        "punctuation_density": punc_density,
        "slv_score": slv_score,
        "ttr_score": ttr_score,
        "llm_score": llm_score,
        "combined_score": combined_score,
        "classification": classification,
        "label_text": label_text
    }
