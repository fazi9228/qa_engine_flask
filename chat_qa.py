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
        # FIXED: Use the OFFICIAL 59 chat reason categories from QA_prompt.md
        # 🔄 FUTURE UPDATES: When new categories are added, just add them to this list below
        # Keep lowercase, use hyphens (not underscores), and add a comment with the date
        self.valid_categories = [
            # Application & Account Setup (1-8)
            'application - status', 'archiving request', 'automated close', 
            'backoffice internal request', 'banned country non-residency check',
            'cash bonus', 'client exit', 'close account',
            
            # Finance & Deposits (9-17)
            'credit card issue', 'crypto trading', 'duplicate case',
            'education/tools', 'escalated to legal & compliance', 
            'feedback responses', 'finance - deposit', 'finance - general',
            'finance - withdrawal',
            
            # General Account & Support (18-21)
            'general account admin', 'general query', 'gold rebate', 
            'ib/partners',
            
            # Technical Issues (22-27)
            'incident / outage', 'instrument depreciation emails',
            'leverage change', 'login issues - my account', 
            'login issues - sca', 'login issues - trading account',
            
            # Marketing & Programs (28-31)
            'marketing', 'mark up increase', 'negative balance adjustment',
            'pepperstone pro q\'s',
            
            # Platforms (32-36)
            'platform - ctrader', 'platform - mac', 'platform - mt4/mt5',
            'platform - pepperstone app', 'platform - pepperstone webtrader',
            
            # Promotions & Regulation (37-39)
            'promotions', 'regulation/licensing', 'sales lead',
            
            # Social & Trading (40-44)
            'social - no response required', 'social - separate case created',
            'social trading/third-party', 'sophisticated investor', 'spams',
            
            # Statements & Support (45-50)
            'statements', 'support internal request', 'swap-free', 'tax',
            'thai bank book', 'trade investigation',
            
            # Trading Conditions (51-55)
            'trading - conditions/instruments', 'trading - issues',
            'tradingview', 'trading - vps', 'unarchiving',
            
            # Website Issues (56-59)
            'website (authenticated) - my account', 
            'website (unauthenticated) - my account',
            'website - main site', 'website - sca'
            
            # ✨ ADD NEW CATEGORIES BELOW THIS LINE ✨
            # Example format:
            # # New Category Group (60-62) - Added YYYY-MM-DD
            # 'new category name',
            # 'another category',
        ]
        
        # Multiple patterns for different chat formats
        self.category_patterns = [
            r'\*\*Chat reason:\s*(.+?)\*\*',        # **Chat reason: General Query**
            r'Chat reason:\s*(.+?)(?:\n|$)',         # Chat reason: General Query
            r'Category:\s*(.+?)(?:\n|$)',            # Category: General Query
            r'Reason for chat:\s*(.+?)(?:\n|$)',     # Reason for chat: ...
            r'Issue type:\s*(.+?)(?:\n|$)',          # Issue type: ...
            r'Topic:\s*(.+?)(?:\n|$)',               # Topic: ...
            r'Subject:\s*(.+?)(?:\n|$)',             # Subject: ...
            r'Type:\s*(.+?)(?:\n|$)',                # Type: ...
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
                category = re.sub(r'[*{}]', '', category).strip()
                category = re.sub(r'[^\w\s\-&/()]', '', category)  # Remove special chars except common ones
                category = category.strip()
                
                if len(category) > 2:  # Ensure it's meaningful
                    return category
        
        return None
    
    def is_valid_category(self, category: Optional[str]) -> bool:
        """
        Check if category matches one of the 59 official categories
        
        Args:
            category: Extracted category or None
            
        Returns:
            True if category is valid (matches official list)
        """
        if not category:
            return False
        
        # Normalize for comparison
        category_lower = category.lower().strip()
        
        # Check for exact or partial match with official categories
        for valid_cat in self.valid_categories:
            # Exact match
            if category_lower == valid_cat:
                return True
            # Partial match (category contains valid category or vice versa)
            if valid_cat in category_lower or category_lower in valid_cat:
                return True
        
        return False
    
    def should_boost_tagging_score(self, category: Optional[str]) -> bool:
        """
        Determine if a valid category was found that should boost tagging scores
        
        Args:
            category: Extracted category or None
            
        Returns:
            True if category should boost tagging scores
        """
        return self.is_valid_category(category)


def extract_chat_category(transcript: str) -> tuple:
    """
    Extract chat category from transcript and determine scoring strategy
    FIXED: Now uses the official 59-category list from QA_prompt.md
    
    Returns: (category, scoring_strategy, should_boost_score)
    """
    extractor = ChatCategoryExtractor()
    
    # Extract category using patterns
    extracted_category = extractor.extract_category(transcript)
    
    if not extracted_category:
        # No category found at all
        return None, "zero", False
    
    # Check if it's a valid official category
    if extractor.is_valid_category(extracted_category):
        # Valid category - boost score
        return extracted_category, "boost", True
    else:
        # Found category but it's not in the official list - penalize
        return extracted_category, "penalize", False


# Function to analyze a transcript with cultural considerations
def analyze_chat_transcript(transcript, rules, kb, target_language="en", prompt_template_path="QA_prompt.md", model_provider="anthropic", model_name=None):
    """
    Analyze a chat transcript using AI models with enhanced category detection
    FIXED: Now correctly validates against official 59 categories
    """
    try:
        # === FORMAT TRANSCRIPT ===
        formatted_transcript = format_transcript_for_ai(transcript)
        
        # === EXTRACT AND VALIDATE CATEGORY ===
        extracted_category, scoring_strategy, should_boost_tagging = extract_chat_category(transcript)
        
        # Enhanced logging with validation details
        if extracted_category:
            if scoring_strategy == "boost":
                print(f"📋 [Category] Found VALID official category: '{extracted_category}' → Boost score 85-95")
            elif scoring_strategy == "penalize":
                print(f"📋 [Category] Found INVALID category: '{extracted_category}' → Penalize score 20-40")
                print(f"    ⚠️ This category is NOT in the official 59-category list!")
        else:
            print("📋 [Category] MISSING → Zero score (0 points)")

        # Set default model name if not provided
        if not model_name:
            if model_provider == "anthropic":
                model_name = "claude-3-7-sonnet-20250219"
            elif model_provider == "openai":
                model_name = "gpt-4o"

        # Use cached language detection
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

        # Prepare KB Context
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
        category_context = ""
        if extracted_category:
            if scoring_strategy == "boost":
                # Valid official category found
                category_context = f"\n\n## ✅ EXCELLENT - Valid Official Chat Categorization Detected:\n"
                category_context += f"This chat has been properly categorized as: '{extracted_category}'\n"
                category_context += f"This category IS in the official 59-category list from Pepperstone.\n"
                category_context += f"✅ SCORING INSTRUCTION: Award 'Tagging & Categorization' parameter a score of 85-95 points. "
                category_context += f"The presence of proper official categorization shows excellent process adherence.\n"
                
            elif scoring_strategy == "penalize":
                # Invalid/wrong category found
                category_context = f"\n\n## ⚠️ POOR - Invalid Chat Categorization Detected:\n"
                category_context += f"This chat has been categorized as: '{extracted_category}'\n"
                category_context += f"❌ CRITICAL ISSUE: This category is NOT in the official 59-category list!\n"
                category_context += f"The agent used an incorrect or custom category instead of the official categories.\n"
                category_context += f"❌ SCORING INSTRUCTION: Award 'Tagging & Categorization' parameter a score of 20-40 points. "
                category_context += f"Wrong categorization is worse than no categorization - it causes reporting errors.\n"
                category_context += f"\n📋 REMINDER: Only these 59 official categories are valid:\n"
                category_context += "1. Application - Status, 2. Archiving request, 3. Automated Close, 4. BackOffice Internal Request, "
                category_context += "5. Banned Country Non-Residency Check, 6. Cash Bonus, 7. Client Exit, 8. Close account, "
                category_context += "9. Credit card issue, 10. Crypto Trading, 11. Duplicate Case, 12. Education/Tools, "
                category_context += "13. Escalated to Legal & Compliance, 14. Feedback Responses, 15. Finance - Deposit, "
                category_context += "16. Finance - General, 17. Finance - Withdrawal, 18. General Account Admin, "
                category_context += "19. General Query, 20-59. [See full list in documentation]\n"
        else:
            # No category found
            category_context = f"\n\n## ❌ CRITICAL - No Chat Categorization Found:\n"
            category_context += f"No system category detected for this chat. This is a critical failure.\n"
            category_context += f"🚨 SCORING INSTRUCTION: Award 'Tagging & Categorization' parameter a score of 0 points. "
            category_context += f"Missing categorization prevents proper tracking and reporting. "
            category_context += f"All customer interactions must be properly categorized using one of the 59 official categories.\n"

        response_text = ""

        if model_provider == "anthropic":
            client = initialize_anthropic_client()
            if not client:
                print("Error: Anthropic API key is required for Claude analysis.")
                return None

            system_prompt = f"""You are a customer support QA analyst for Pepperstone, a forex broker.
            You will analyze customer support transcripts and score them on quality parameters.
            YOUR RESPONSE MUST BE IN VALID JSON FORMAT.
            
            CRITICAL: For 'Tagging & Categorization' parameter, ONLY the 59 official Pepperstone categories are valid.
            Any other category (including Knowledge Base categories) is INCORRECT.
            
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
            Your response must be a valid JSON object. Use the full scoring range 0-100.
            
            CRITICAL: For 'Tagging & Categorization', only the 59 official Pepperstone categories are valid."""

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
            print(f"Response preview: {response_text[:1000]}")
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
        analysis["category_is_valid_official"] = scoring_strategy == "boost"  # NEW: Clear indicator

        return analysis

    except Exception as e:
        print(f"Error analyzing transcript: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return None
    
    
def create_downloadable_json(result):
    """Create a properly formatted JSON string for download"""
    try:
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error creating downloadable JSON: {str(e)}")
        return json.dumps({"error": "Failed to format results"}, indent=2)

def create_downloadable_csv(result, rules):
    """Create a CSV string from analysis results for download"""
    try:
        csv_data = "Parameter,Score,Has Suggestion\n"
        
        for param in rules["parameters"]:
            param_name = param["name"]
            if param_name in result and isinstance(result[param_name], dict):
                score = result[param_name].get("score", "N/A")
                has_suggestion = "Yes" if result[param_name].get("suggestion") else "No"
                param_name_escaped = f'"{param_name}"' if ',' in param_name else param_name
                csv_data += f'{param_name_escaped},{score},{has_suggestion}\n'
        
        return csv_data
    except Exception as e:
        print(f"Error creating downloadable CSV: {str(e)}")
        return "Parameter,Score,Has Suggestion\nError,N/A,No\n"

def create_batch_csv(results, rules):
    """Create a detailed CSV for batch analysis results"""
    try:
        csv_data = "Chat ID,Parameter,Score,Explanation,Example,Suggestion\n"
        
        for result in results:
            chat_id = result.get('chat_id', 'Unknown')
            
            for param in rules["parameters"]:
                param_name = param["name"]
                if param_name in result and isinstance(result[param_name], dict):
                    param_data = result[param_name]
                    score = param_data.get("score", "N/A")
                    
                    explanation = str(param_data.get("explanation", "")).replace('"', '""')
                    example = str(param_data.get("example", "")).replace('"', '""')
                    suggestion = str(param_data.get("suggestion", "N/A")).replace('"', '""')
                    
                    if suggestion in ["None", "null", "NULL"]:
                        suggestion = "N/A"
                    
                    csv_data += f'"{chat_id}","{param_name}",{score},"{explanation}","{example}","{suggestion}"\n'
        
        return csv_data
    except Exception as e:
        print(f"Error creating batch CSV: {str(e)}")
        return "Chat ID,Parameter,Score,Explanation,Example,Suggestion\nError,Error,N/A,Failed to generate report,N/A,N/A\n"

def get_quality_level_from_score(score, rules):
    """Determine quality level based on score and rules"""
    try:
        if "scoring_system" in rules and "quality_levels" in rules["scoring_system"]:
            for level in rules["scoring_system"]["quality_levels"]:
                if level["range"]["min"] <= score <= level["range"]["max"]:
                    return level["name"]
        
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
    """Get CSS color class based on quality level"""
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
        return "score-box-needs-improvement"

def validate_analysis_result(result, rules):
    """Validate that analysis result has all required parameters"""
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
    """Enhance analysis result with additional metadata and validation"""
    if not result:
        return None
    
    try:
        result["analysis_timestamp"] = datetime.now().isoformat()
        
        overall_score = result.get("weighted_overall_score", 0)
        result["quality_level"] = get_quality_level_from_score(overall_score, rules)
        result["quality_color_class"] = get_quality_color_class(result["quality_level"])
        
        for param in rules["parameters"]:
            param_name = param["name"]
            if param_name not in result:
                result[param_name] = {
                    "score": 50,
                    "explanation": "No analysis available for this parameter",
                    "example": "N/A",
                    "suggestion": "Please review manually"
                }
        
        return result
        
    except Exception as e:
        print(f"Error enhancing analysis result: {str(e)}")
        return result
