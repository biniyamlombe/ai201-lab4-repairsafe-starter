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

def get_heuristic_score(slv, ttr, word_count):
    """
    Combines SLV and TTR into a heuristic score between 0.0 (Human) and 1.0 (AI).
    If text is too short, return a neutral 0.5.
    """
    if word_count < 50:
        return 0.5
        
    # SLV mapping: Variance > 25 is human (0.0 AI score); Variance < 4 is AI (1.0 AI score)
    # Clamp SLV between 4 and 25
    clamped_slv = max(4.0, min(25.0, slv))
    slv_score = 1.0 - ((clamped_slv - 4.0) / (25.0 - 4.0))
    
    # TTR mapping: TTR > 0.65 is human (0.0 AI score); TTR < 0.45 is AI (1.0 AI score)
    # Clamp TTR between 0.45 and 0.65
    clamped_ttr = max(0.45, min(0.65, ttr))
    ttr_score = 1.0 - ((clamped_ttr - 0.45) / (0.65 - 0.45))
    
    # Weighted average of SLV and TTR
    return 0.5 * slv_score + 0.5 * ttr_score

def get_llm_score(text):
    """
    Calls Groq Llama-3.3-70b-versatile to evaluate text semantic patterns.
    Returns a score between 0.0 and 1.0.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is not set.")
        
    client = Groq(api_key=api_key)
    
    system_prompt = (
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

def analyze_content(text):
    """
    Orchestrates the multi-signal detection pipeline.
    Returns a dictionary with scores, classification, and label.
    """
    words = get_words(text)
    word_count = len(words)
    
    # Calculate Signal 1: Heuristics
    slv = calculate_slv(text)
    ttr = calculate_ttr(text)
    punc_density = calculate_punctuation_density(text)
    heuristic_score = get_heuristic_score(slv, ttr, word_count)
    
    # Calculate Signal 2: LLM
    try:
        llm_score = get_llm_score(text)
    except Exception as e:
        print(f"LLM signal failed: {e}. Falling back to heuristic-only scoring.")
        llm_score = heuristic_score
        
    # Ensemble combination: weight LLM 70% and Heuristics 30%
    # If text is too short (< 50 words), heuristics are unreliable, rely only on LLM
    if word_count < 50:
        combined_score = llm_score
    else:
        combined_score = 0.3 * heuristic_score + 0.7 * llm_score
        
    # Categorization based on asymmetric false positive prevention thresholds
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
        "heuristic_score": heuristic_score,
        "llm_score": llm_score,
        "combined_score": combined_score,
        "classification": classification,
        "label_text": label_text
    }
