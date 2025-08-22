import json
from datetime import datetime
import concurrent.futures
from knowledge_base import KnowledgeBase
from chat_formatter import format_transcript_for_ai
import re
from typing import Optional, Dict, Tuple

# Import utilities from utils.py
from utils import (
    initialize_anthropic_client, 
    initialize_openai_client, 
    parse_json_response, 
    detect_language,
    detect_language_cached,
    load_prompt_template,
    load_evaluation_rules
)

class ChatCategoryExtractor:
    """Handles category extraction from chat transcripts"""
    
    def __init__(self):
        # Multiple patterns for different chat formats
        self.category_patterns = [
            r'Chat reason:\s*(.+?)(?:\n|$)',
            r'Category:\s*(.+?)(?:\n|$)', 
            r'Reason for chat:\s*(.+?)(?:\n|$)',
            r'Issue type:\s*(.+?)(?:\n|$)',
            r'Topic:\s*(.+?)(?:\n|$)',
            r'Subject:\s*(.+?)(?:\n|$)',
            r'Type:\s*(.+?)(?:\n|$)',
        ]
    
    def extract_category(self, transcript: str) -> Optional[str]:
        """
        Extract category from chat transcript using multiple patterns
        
        Args:
            transcript: Raw chat transcript
            
        Returns:
            Category string if found, None otherwise
        """
        for pattern in self.category_patterns:
            match = re.search(pattern, transcript, re.IGNORECASE | re.MULTILINE)
            if match:
                category = match.group(1).strip()
                # Clean up common artifacts
                category = re.sub(r'[^\w\s\-&/]', '', category)  # Remove special chars except common ones
                category = category.strip()
                
                if len(category) > 2:  # Ensure it's meaningful
                    return category
        
        return None
    
    def should_boost_tagging_score(self, category: Optional[str]) -> bool:
        """
        Determine if a valid category was found that should boost tagging scores
        
        Args:
            category: Extracted category or None
            
        Returns:
            True if category should boost tagging scores
        """
        if not category:
            return False
        
        # Filter out generic/meaningless categories
        generic_categories = [
            'general', 'misc', 'other', 'unknown', 'n/a', 'na', 
            'support', 'help', 'question', 'inquiry'
        ]
        
        return category.lower().strip() not in generic_categories


def extract_chat_category(transcript: str) -> tuple:
    """
    Extract chat category from transcript and determine scoring strategy
    Returns: (category, scoring_strategy, should_boost_score)
    """
    # Pattern specifically for your format: **Chat reason: General Query**
    category_patterns = [
        r'\*\*Chat reason:\s*(.+?)\*\*',  # **Chat reason: General Query**
        r'Chat reason:\s*(.+?)(?:\n|$)',   # Chat reason: General Query
        r'Category:\s*(.+?)(?:\n|$)',      # Category: General Query
        r'Issue type:\s*(.+?)(?:\n|$)',    # Issue type: General Query
        r'Topic:\s*(.+?)(?:\n|$)',         # Topic: General Query
    ]
    
    # Known valid categories - UPDATE THIS LIST based on your business needs
    valid_categories =  [
        'general query', 'account types', 'trading platforms', 'leverage change',
        'finance - general', 'deposits & withdrawals', 'technical support',
        'account verification', 'platform issues', 'trading questions',
        'compliance', 'kyc', 'documentation', 'payment issues'
    ]
    
    for pattern in category_patterns:
        match = re.search(pattern, transcript, re.IGNORECASE | re.MULTILINE)
        if match:
            category = match.group(1).strip()
            # Clean up any remaining markdown or special characters
            category = re.sub(r'[*{}]', '', category).strip()
            
            if len(category) > 2:
                # Check if category is valid/recognized
                category_lower = category.lower()
                
                # Exact match or contains valid category
                is_valid_category = any(valid_cat in category_lower for valid_cat in valid_categories)
                
                if is_valid_category:
                    return category, "boost", True  # Found valid category - boost score
                else:
                    return category, "penalize", False  # Found category but it's wrong/unrecognized
    
    return None, "zero", False  # No category found - give 0 points


# Function to analyze a transcript with cultural considerations
def analyze_chat_transcript(transcript, rules, kb, target_language="en", prompt_template_path="QA_prompt.md", model_provider="anthropic", model_name=None):
    """
    Analyze a chat transcript using AI models with enhanced category detection
    """
    try:
        # === FORMAT TRANSCRIPT ===
        formatted_transcript = format_transcript_for_ai(transcript)
        
        # === EXTRACT CATEGORY ===
        extracted_category, scoring_strategy, should_boost_tagging = extract_chat_category(transcript)
        
        if extracted_category:
            if scoring_strategy == "boost":
                print(f"📋 [Category] Found VALID: '{extracted_category}' → Boost score 85-95")
            elif scoring_strategy == "penalize":
                print(f"📋 [Category] Found INVALID: '{extracted_category}' → Penalize score 20-40")
        else:
            print("📋 [Category] MISSING → Zero score (0 points)")


        # Set default model name if not provided
        if not model_name:
            if model_provider == "anthropic":
                model_name = "claude-3-7-sonnet-20250219"
            elif model_provider == "openai":
                model_name = "gpt-4o"

        # Use cached language detection on the ORIGINAL transcript if needed,
        # but use the FORMATTED transcript for the main analysis.
        text_sample = transcript[:200]
        _, lang_name = detect_language_cached(text_sample, model_provider)

        # Extract parameters and build list
        parameters_list = ""
        for param in rules["parameters"]:
            parameters_list += f"- {param['name']}: {param['description']}\n"

        # Extract scoring scale information
        scale_max = 100
        if "scoring_system" in rules and "score_scale" in rules["scoring_system"]:
            scale_max = rules["scoring_system"]["score_scale"]["max"]

        # Get scoring system info
        scoring_info = ""
        if "scoring_system" in rules and "quality_levels" in rules["scoring_system"]:
            scoring_info = "Use the following scoring scale:\n"
            for level in rules["scoring_system"]["quality_levels"]:
                scoring_info += f"- {level['name']} ({level['range']['min']}-{level['range']['max']}): {level['description']}\n"

        # Load prompt template
        prompt_template = load_prompt_template(prompt_template_path)
        if not prompt_template:
            print(f"Error: Could not load prompt template from {prompt_template_path}")
            return None

        # Prepare KB Context with clearer instructions
        kb_context = "\n\n## Internal Knowledge Base Guidance:\n"
        kb_context += "The following are standard answers from our knowledge base for common questions. "
        kb_context += "Only evaluate Knowledge Base adherence when customer questions clearly match KB content. "
        kb_context += "For questions not covered in the KB, the agent should use their expertise appropriately. "
        kb_context += "Focus on identifying contradictions with KB rather than expecting exact matches.\n\n"

        kb_qa_pairs = kb.qa_pairs.get("qa_pairs", [])
        if kb_qa_pairs:
            for i, qa_pair in enumerate(kb_qa_pairs[:20]):  # Limit to 20 entries
                kb_context += f"Q: {qa_pair.get('question', '')}\n"
                kb_context += f"A: {qa_pair.get('answer', '')}\n"
                kb_context += f"Category: {qa_pair.get('category', 'General')}\n\n"
        else:
            kb_context += "The knowledge base is currently empty. Evaluate based on general accuracy and procedures.\n"

        # === CATEGORY-AWARE SCORING INSTRUCTIONS ===
        # === ENHANCED CATEGORY-AWARE SCORING INSTRUCTIONS ===
        category_context = ""
        if extracted_category:
            if scoring_strategy == "boost":
                # Valid category found - boost score
                category_context = f"\n\n## ✅ EXCELLENT - Valid Chat Categorization Detected:\n"
                category_context += f"This chat has been properly categorized as: '{extracted_category}'\n"
                category_context += f"✅ SCORING INSTRUCTION: Since a VALID system category was found, "
                category_context += f"award 'Tagging & Categorization' parameter a score of 85-95 points. "
                category_context += f"The presence of proper categorization shows excellent process adherence.\n"
                
            elif scoring_strategy == "penalize":
                # Invalid/wrong category found - penalize
                category_context = f"\n\n## ⚠️ POOR - Invalid Chat Categorization Detected:\n"
                category_context += f"This chat has been categorized as: '{extracted_category}'\n"
                category_context += f"❌ SCORING INSTRUCTION: The category appears to be INCORRECT or UNRECOGNIZED. "
                category_context += f"Award 'Tagging & Categorization' parameter a score of 20-40 points. "
                category_context += f"Wrong categorization is worse than no categorization.\n"
        else:
            # No category found - zero score
            category_context = f"\n\n## ❌ CRITICAL - No Chat Categorization Found:\n"
            category_context += f"No system category detected for this chat. This is a critical failure.\n"
            category_context += f"🚨 SCORING INSTRUCTION: Award 'Tagging & Categorization' parameter a score of 0 points. "
            category_context += f"Missing categorization prevents proper tracking and reporting. "
            category_context += f"All customer interactions must be properly categorized.\n"

        response_text = ""

        if model_provider == "anthropic":
            client = initialize_anthropic_client()
            if not client:
                print("Error: Anthropic API key is required for Claude analysis.")
                return None

            system_prompt = f"""You are a customer support QA analyst for Pepperstone, a forex broker.
            You will analyze customer support transcripts and score them on quality parameters.
            YOUR RESPONSE MUST BE IN VALID JSON FORMAT.
            
            You will evaluate how well the agent's responses match the Knowledge Base answers when a customer asks a question covered in the KB.
            
            IMPORTANT: Use the full 0-100 scoring range. Award 90+ for excellent performance, 70-89 for good, 50-69 for adequate, and below 50 for poor performance.
            
            You MUST return your analysis ONLY as a valid, parseable JSON object with no additional text, explanations, or markdown.
            The JSON must have parameters as keys, each containing a nested object with 'score', 'explanation', 'example', and 'suggestion' fields.
            """

            user_prompt = f"""Analyze this customer support transcript and score EACH parameter listed below. 
            Return your analysis ONLY as a valid JSON object.
            
            Parameters to evaluate:
            {parameters_list}
            
            {scoring_info}
            
            {kb_context}
            
            {category_context}
            
            Transcript to analyze:
            {formatted_transcript}
            
            Remember: Use the full 0-100 scoring range. Award 90+ for excellent performance.
            Pay special attention to the categorization information provided above when scoring 'Tagging & Categorization'.
            Your response must be a single valid JSON object with no additional text.
            Each parameter must be a key in the JSON, with a nested object containing 'score', 'explanation', 'example', and 'suggestion' fields.
            
            Example format:
            {{
              "Parameter Name 1": {{
                "score": 85,
                "explanation": "Explanation text",
                "example": "Example from transcript",
                "suggestion": "Improvement suggestion"
              }},
              "Parameter Name 2": {{
                "score": 90,
                "explanation": "Explanation text",
                "example": "Example from transcript", 
                "suggestion": "Improvement suggestion"
              }}
            }}
            """

            try:
                response = client.messages.create(
                    model=model_name,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    max_tokens=4000,
                    temperature=0.0
                )
                response_text = response.content[0].text

            except Exception as claude_error:
                print(f"Claude API error: {str(claude_error)}")
                return None

        elif model_provider == "openai":
            client = initialize_openai_client()
            if not client:
                print("Error: OpenAI API key is required for GPT analysis.")
                return None

            system_prompt = f"""You are a QA analyst for Pepperstone, a forex broker. Score the support transcript according to the rules and context provided. 
            Your response must be a valid JSON object. Use the full scoring range 0-100."""

            user_prompt = f"""Score this support transcript on a scale of 0-{scale_max} for EXACTLY these parameters:
            {parameters_list}
            
            {scoring_info}
            
            {kb_context}
            
            {category_context}
            
            Transcript to analyze:
            {formatted_transcript}
            
            Pay special attention to the categorization information when scoring 'Tagging & Categorization'.
            Return your analysis as a JSON object with each parameter as a key, containing a nested object with 'score', 'explanation', 'example', and 'suggestion' fields.
            """

            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.0
                )
                response_text = response.choices[0].message.content

            except Exception as openai_error:
                print(f"OpenAI API error: {str(openai_error)}")
                return None

        else:
            print(f"Error: Unsupported model provider: {model_provider}")
            return None

        # Parse the response
        analysis = parse_json_response(response_text)

        if not analysis:
            print("Error: Failed to parse API response to JSON")
            print(f"Response preview: {response_text[:1000]}")  # Show first 1000 chars
            return None

        # Calculate weighted score
        total_weight = sum(param["weight"] for param in rules["parameters"])
        weighted_score = 0
        missing_params = []

        for param in rules["parameters"]:
            param_name = param["name"]
            if param_name in analysis and isinstance(analysis[param_name], dict) and "score" in analysis[param_name]:
                score_value = analysis[param_name]["score"]
                if isinstance(score_value, (int, float)):
                    weighted_score += score_value * param["weight"]
                else:
                    print(f"Warning: Invalid score type for parameter '{param_name}': {score_value}")
                    missing_params.append(f"{param_name} (invalid score)")
            else:
                missing_params.append(param_name)

        if missing_params:
            print(f"Warning: Parameters missing or invalid in API response: {', '.join(missing_params)}")

        # Calculate final weighted score
        if total_weight > 0:
            weighted_score = weighted_score / total_weight
        else:
            weighted_score = 0

        analysis["weighted_overall_score"] = round(weighted_score, 2)
        analysis["model_provider"] = model_provider
        analysis["model_name"] = model_name
        
        # Add category metadata for transparency and debugging
        analysis["extracted_category"] = extracted_category
        analysis["category_scoring_strategy"] = scoring_strategy
        analysis["category_boost_applied"] = should_boost_tagging

        return analysis

    except Exception as e:
        print(f"Error analyzing transcript: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None
    
    
def create_downloadable_json(result):
    """
    Create a properly formatted JSON string for download
    
    Args:
        result (dict): Analysis result dictionary
        
    Returns:
        str: Formatted JSON string
    """
    try:
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error creating downloadable JSON: {str(e)}")
        return json.dumps({"error": "Failed to format results"}, indent=2)

def create_downloadable_csv(result, rules):
    """
    Create a CSV string from analysis results for download
    
    Args:
        result (dict): Analysis result dictionary
        rules (dict): Evaluation rules dictionary
        
    Returns:
        str: CSV formatted string
    """
    try:
        csv_data = "Parameter,Score,Has Suggestion\n"
        
        for param in rules["parameters"]:
            param_name = param["name"]
            if param_name in result and isinstance(result[param_name], dict):
                score = result[param_name].get("score", "N/A")
                has_suggestion = "Yes" if result[param_name].get("suggestion") else "No"
                # Escape parameter name for CSV
                param_name_escaped = f'"{param_name}"' if ',' in param_name else param_name
                csv_data += f'{param_name_escaped},{score},{has_suggestion}\n'
        
        return csv_data
    except Exception as e:
        print(f"Error creating downloadable CSV: {str(e)}")
        return "Parameter,Score,Has Suggestion\nError,N/A,No\n"

def create_batch_csv(results, rules):
    """
    Create a detailed CSV for batch analysis results
    
    Args:
        results (list): List of analysis result dictionaries
        rules (dict): Evaluation rules dictionary
        
    Returns:
        str: CSV formatted string
    """
    try:
        csv_data = "Chat ID,Parameter,Score,Explanation,Example,Suggestion\n"
        
        for result in results:
            chat_id = result.get('chat_id', 'Unknown')
            
            for param in rules["parameters"]:
                param_name = param["name"]
                if param_name in result and isinstance(result[param_name], dict):
                    param_data = result[param_name]
                    score = param_data.get("score", "N/A")
                    
                    # Clean and escape text fields for CSV
                    explanation = str(param_data.get("explanation", "")).replace('"', '""')
                    example = str(param_data.get("example", "")).replace('"', '""')
                    suggestion = str(param_data.get("suggestion", "N/A")).replace('"', '""')
                    
                    # Handle None values
                    if suggestion in ["None", "null", "NULL"]:
                        suggestion = "N/A"
                    
                    csv_data += f'"{chat_id}","{param_name}",{score},"{explanation}","{example}","{suggestion}"\n'
        
        return csv_data
    except Exception as e:
        print(f"Error creating batch CSV: {str(e)}")
        return "Chat ID,Parameter,Score,Explanation,Example,Suggestion\nError,Error,N/A,Failed to generate report,N/A,N/A\n"

def get_quality_level_from_score(score, rules):
    """
    Determine quality level based on score and rules
    
    Args:
        score (float): The overall score
        rules (dict): Evaluation rules dictionary
        
    Returns:
        str: Quality level name
    """
    try:
        # Use scoring system from rules if available
        if "scoring_system" in rules and "quality_levels" in rules["scoring_system"]:
            for level in rules["scoring_system"]["quality_levels"]:
                if level["range"]["min"] <= score <= level["range"]["max"]:
                    return level["name"]
        
        # Fallback to simple quality level determination
        if score >= 85:
            return "Excellent"
        elif score >= 70:
            return "Good"
        elif score >= 50:
            return "Needs Improvement"
        else:
            return "Poor"
    except Exception as e:
        print(f"Error determining quality level: {str(e)}")
        return "Unknown"

def get_quality_color_class(quality_level):
    """
    Get CSS color class based on quality level
    
    Args:
        quality_level (str): Quality level name
        
    Returns:
        str: CSS class name
    """
    quality_level_lower = quality_level.lower()
    
    if "excellent" in quality_level_lower:
        return "score-box-excellent"
    elif "good" in quality_level_lower:
        return "score-box-good"
    elif "needs improvement" in quality_level_lower or "improvement" in quality_level_lower:
        return "score-box-needs-improvement"
    elif "poor" in quality_level_lower:
        return "score-box-poor"
    else:
        return "score-box-needs-improvement"  # Default

def validate_analysis_result(result, rules):
    """
    Validate that analysis result has all required parameters
    
    Args:
        result (dict): Analysis result dictionary
        rules (dict): Evaluation rules dictionary
        
    Returns:
        tuple: (is_valid, missing_parameters)
    """
    if not result or not isinstance(result, dict):
        return False, ["Invalid result structure"]
    
    missing_params = []
    
    for param in rules["parameters"]:
        param_name = param["name"]
        if param_name not in result:
            missing_params.append(param_name)
        elif not isinstance(result[param_name], dict):
            missing_params.append(f"{param_name} (invalid structure)")
        elif "score" not in result[param_name]:
            missing_params.append(f"{param_name} (missing score)")
    
    return len(missing_params) == 0, missing_params

def enhance_analysis_result(result, rules):
    """
    Enhance analysis result with additional metadata and validation
    
    Args:
        result (dict): Analysis result dictionary
        rules (dict): Evaluation rules dictionary
        
    Returns:
        dict: Enhanced analysis result
    """
    if not result:
        return None
    
    try:
        # Add timestamp
        result["analysis_timestamp"] = datetime.now().isoformat()
        
        # Add quality level
        overall_score = result.get("weighted_overall_score", 0)
        result["quality_level"] = get_quality_level_from_score(overall_score, rules)
        result["quality_color_class"] = get_quality_color_class(result["quality_level"])
        
        # Validate and fill missing parameters
        for param in rules["parameters"]:
            param_name = param["name"]
            if param_name not in result:
                result[param_name] = {
                    "score": 50,  # Default neutral score
                    "explanation": "No analysis available for this parameter",
                    "example": "N/A",
                    "suggestion": "Please review manually"
                }
        
        return result
        
    except Exception as e:
        print(f"Error enhancing analysis result: {str(e)}")
        return result
