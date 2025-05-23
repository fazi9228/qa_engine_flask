import json
import os
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
import re

# Import libraries for API access
import anthropic
import openai

# Global client variables for lazy loading
_anthropic_client = None
_openai_client = None

# Enhanced API key handling with Flask integration
def get_api_key(provider="anthropic"):
    """
    Get the API key from various sources in the following priority order:
    1. Flask session (if manually entered in UI)
    2. Environment variable
    
    Args:
        provider (str): The API provider ("anthropic" or "openai")
    """
    # Check if we're in Flask context
    try:
        from flask import session
        flask_available = True
    except ImportError:
        flask_available = False
    
    # Check session state first (if user manually entered it) - only if Flask is available
    if flask_available:
        try:
            if f'{provider}_key' in session:
                return session[f'{provider}_key']
        except RuntimeError:
            # Outside of Flask application context
            pass
    
    # Check environment variables
    env_var_names = {
        "anthropic": ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"],
        "openai": ["OPENAI_API_KEY"]
    }
    
    for env_var in env_var_names.get(provider, []):
        api_key = os.environ.get(env_var)
        if api_key:
            return api_key
    
    # No API key found
    return None

# Initialize Anthropic client with lazy loading and proper Flask context handling
def initialize_anthropic_client():
    global _anthropic_client
    
    # Always check for fresh API key in case it was updated in session
    api_key = get_api_key("anthropic")
    if not api_key:
        print("No Anthropic API key found")
        return None
        
    # If we already have a client, check if it's using the same key
    # For security, we can't directly compare keys, so we'll recreate if needed
    try:
        if _anthropic_client is None:
            _anthropic_client = anthropic.Anthropic(api_key=api_key)
            print("Initialized new Anthropic client")
        return _anthropic_client
    except Exception as e:
        print(f"Error initializing Anthropic client: {str(e)}")
        _anthropic_client = None
        return None

# Initialize OpenAI client with lazy loading and proper Flask context handling
def initialize_openai_client():
    global _openai_client
    
    # Always check for fresh API key in case it was updated in session
    api_key = get_api_key("openai")
    if not api_key:
        print("No OpenAI API key found")
        return None
        
    try:
        if _openai_client is None:
            _openai_client = openai.OpenAI(api_key=api_key)
            
            # Test the client with a minimal request to verify it works
            try:
                test_response = _openai_client.models.list()
                print("Initialized and tested OpenAI client successfully")
            except Exception as test_error:
                print(f"OpenAI client test failed: {str(test_error)}")
                _openai_client = None
                return None
                
        return _openai_client
    except Exception as e:
        print(f"Error initializing OpenAI client: {str(e)}")
        _openai_client = None
        return None

# Reset client connections (useful when API keys change)
def reset_api_clients():
    """Reset all API clients to force re-initialization with fresh keys"""
    global _anthropic_client, _openai_client
    _anthropic_client = None
    _openai_client = None
    print("Reset all API clients")

# Helper function to parse JSON from API responses with better error handling
def parse_json_response(response_text):
    """Parse JSON from API responses with better error handling"""
    try:
        # Try direct JSON parsing first
        return json.loads(response_text)
    except json.JSONDecodeError:
        # If direct parsing fails, try to extract JSON from text
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        if json_start != -1 and json_end != -1:
            json_str = response_text[json_start:json_end]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # Try one more approach - look for ```json blocks
                import re
                json_blocks = re.findall(r'```json\s*([\s\S]*?)\s*```', response_text)
                if json_blocks:
                    try:
                        return json.loads(json_blocks[0])
                    except json.JSONDecodeError:
                        print("Failed to extract valid JSON from API response")
                        return None
                else:
                    print("Failed to extract valid JSON from API response")
                    return None
        else:
            print("Could not find JSON structure in API response")
            return None

# Create a simple cache for language detection to avoid repeated API calls
_language_cache = {}

def detect_language_cached(text_sample, model_provider):
    """Cached wrapper for language detection - takes a sample to reduce cache size"""
    # Only use the first 200 chars for caching purposes
    text_sample = text_sample[:200]
    
    # Create cache key
    cache_key = f"{model_provider}:{hash(text_sample)}"
    
    # Check cache first
    if cache_key in _language_cache:
        return _language_cache[cache_key]
    
    # If not in cache, detect language
    result = detect_language_smart(text_sample, model_provider)
    
    # Store in cache (limit cache size)
    if len(_language_cache) > 100:
        # Clear old entries when cache gets too large
        _language_cache.clear()
    
    _language_cache[cache_key] = result
    return result

def extract_customer_messages(transcript):
    """
    Extract customer messages after chat transfer to agent for better language detection
    """
    lines = transcript.split('\n')
    customer_messages = []
    
    print(f"Analyzing transcript with {len(lines)} lines")
    
    # Show sample lines to understand the format
    print("Sample lines from transcript:")
    for i, line in enumerate(lines[:15]):  # Show more lines
        print(f"  Line {i}: '{line.strip()}'")
    
    # Find where the actual chat with agent starts
    chat_started = False
    transfer_indicators = [
        r'Chat Transferred From.*To Support',
        r'Agent.*successfully transferred',
        r'transferred.*to skill',
        r'Chat Origin:',
        r'Support:'  # When we see first Support message, chat has started
    ]
    
    for line_num, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Check if chat has started with agent
        if not chat_started:
            for indicator in transfer_indicators:
                if re.search(indicator, line, re.IGNORECASE):
                    chat_started = True
                    print(f"Found transfer indicator at line {line_num}: '{line[:60]}'")
                    break
        
        # Only start collecting customer messages after chat has started
        if chat_started:
            # Look for any line that contains "Visitor:" after a timestamp
            if 'Visitor:' in line and line.startswith('('):
                print(f"Examining visitor line: '{line}'")
                
                # Split at "Visitor:" and take everything after it
                parts = line.split('Visitor:', 1)
                if len(parts) == 2:
                    message_content = parts[1].strip()
                    
                    if message_content and len(message_content.strip()) > 3:
                        customer_messages.append(message_content.strip())
                        print(f"✅ Found customer message: '{message_content[:50]}...'")
                    else:
                        print(f"❌ Message too short: '{message_content}'")
                else:
                    print(f"❌ Could not split line at 'Visitor:': '{line}'")
            
            # Also check for potential visitor messages that don't match
            elif 'Visitor' in line and ':' in line:
                print(f"⚠️ Potential visitor message not matched: '{line}'")
    
    print(f"Extracted {len(customer_messages)} customer messages after transfer")
    if customer_messages:
        print(f"Sample messages: {customer_messages[:3]}")
    
    customer_text = ' '.join(customer_messages)
    print(f"Final customer text length: {len(customer_text)}")
    print(f"Final customer text: '{customer_text[:200]}...'")
    
    return customer_text if customer_text else transcript[:500]

def detect_language_with_llm(text, model_provider="anthropic", model_name=None):
    """
    Use the same LLM that processes chats to detect language
    Much more accurate than frequency-based detection
    """
    try:
        print(f"=== LLM LANGUAGE DETECTION ===")
        print(f"Text sample: '{text[:100]}...' (length: {len(text)})")
        
        # Get the appropriate client
        if model_provider == "anthropic":
            client = initialize_anthropic_client()
            if not client:
                return "en", "English (no API key)"
            
            model_to_use = model_name or "claude-3-7-sonnet-20250219"
            
            prompt = f"""Analyze this text and determine what language it is written in.

Text to analyze:
{text[:800]}

Instructions:
- Look at the actual customer/visitor messages, ignore system messages
- Focus on the language used by humans in conversation
- Common languages: English, Vietnamese, Thai, Chinese, Spanish, Portuguese, French
- Respond with just the language name, nothing else
- If multiple languages, choose the predominant one used by customers"""

            response = client.messages.create(
                model=model_to_use,
                max_tokens=20,
                messages=[{"role": "user", "content": prompt}]
            )
            
            detected_language = response.content[0].text.strip()
            
        elif model_provider == "openai":
            client = initialize_openai_client()
            if not client:
                return "en", "English (no API key)"
            
            model_to_use = model_name or "gpt-4o"
            
            prompt = f"""Analyze this text and determine what language it is written in.

Text to analyze:
{text[:800]}

Instructions:
- Look at the actual customer/visitor messages, ignore system messages
- Focus on the language used by humans in conversation
- Common languages: English, Vietnamese, Thai, Chinese, Spanish, Portuguese, French
- Respond with just the language name, nothing else
- If multiple languages, choose the predominant one used by customers"""

            response = client.chat.completions.create(
                model=model_to_use,
                max_tokens=20,
                messages=[{"role": "user", "content": prompt}]
            )
            
            detected_language = response.choices[0].message.content.strip()
        
        else:
            return "en", "English (unsupported provider)"
        
        # Clean up the response
        detected_language = detected_language.lower().strip()
        
        # Map common variations to standard names
        language_mapping = {
            'vietnamese': 'Vietnamese',
            'tiếng việt': 'Vietnamese',
            'việt': 'Vietnamese',
            'english': 'English',
            'thai': 'Thai',
            'ภาษาไทย': 'Thai',
            'chinese': 'Chinese',
            'mandarin': 'Chinese',
            '中文': 'Chinese',
            'spanish': 'Spanish',
            'español': 'Spanish',
            'portuguese': 'Portuguese',
            'português': 'Portuguese',
            'french': 'French',
            'français': 'French'
        }
        
        # Find matching language
        final_language = None
        for key, value in language_mapping.items():
            if key in detected_language:
                final_language = value
                break
        
        if not final_language:
            # If no match found, capitalize the detected language
            final_language = detected_language.title()
        
        # Generate language code
        language_codes = {
            'Vietnamese': 'vi',
            'English': 'en', 
            'Thai': 'th',
            'Chinese': 'zh',
            'Spanish': 'es',
            'Portuguese': 'pt',
            'French': 'fr'
        }
        
        language_code = language_codes.get(final_language, 'en')
        
        print(f"LLM detected: '{detected_language}' -> {language_code}, {final_language}")
        return language_code, final_language
        
    except Exception as e:
        print(f"LLM language detection error: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return "en", "English (detection error)"

def detect_language_smart(transcript, model_provider="anthropic"):
    """
    Smart language detection using LLM - much more accurate
    
    Args:
        transcript (str): Full chat transcript
        model_provider (str): AI provider to use
        
    Returns:
        tuple: (language_code, language_name)
    """
    try:
        print(f"=== SMART LANGUAGE DETECTION (LLM-based) ===")
        
        # First try to extract customer messages for more focused detection
        customer_text = extract_customer_messages(transcript)
        
        # Choose what text to analyze
        if customer_text and len(customer_text.strip()) > 20:
            text_to_analyze = customer_text
            print(f"Using extracted customer messages ({len(customer_text)} chars)")
        else:
            # Use full transcript but focus on the middle part where customer messages likely are
            text_to_analyze = transcript
            print(f"Using full transcript ({len(transcript)} chars)")
        
        # Use LLM for detection
        return detect_language_with_llm(text_to_analyze, model_provider)
        
    except Exception as e:
        print(f"Smart language detection error: {str(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        return "en", "English (complete fallback)"

def detect_language_smart_cached(transcript, model_provider):
    """Cached version of smart language detection"""
    # Create cache key from customer messages only
    customer_text = extract_customer_messages(transcript)
    cache_key = f"{model_provider}:{hash(customer_text[:200])}"
    
    # Check cache first
    if cache_key in _language_cache:
        return _language_cache[cache_key]
    
    # If not in cache, detect language
    result = detect_language_smart(transcript, model_provider)
    
    # Store in cache (limit cache size)
    if len(_language_cache) > 100:
        # Clear old entries when cache gets too large
        _language_cache.clear()
    
    _language_cache[cache_key] = result
    return result

# LEGACY FUNCTION - kept for backward compatibility but not recommended
def detect_language(text, model_provider="anthropic"):
    """
    Legacy detect language function - calls the smart version
    """
    print("WARNING: Using legacy detect_language function. Consider using detect_language_smart instead.")
    return detect_language_smart(text, model_provider)

# Function to load the prompt template from a markdown file
def load_prompt_template(file_path="QA_prompt.md"):
    """
    Load the QA prompt template from a markdown file
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            prompt_template = f.read()
        return prompt_template
    except FileNotFoundError:
        print(f"Prompt template file '{file_path}' not found. This file is required.")
        return None

# Function to load evaluation rules from JSON file
def load_evaluation_rules(file_path="evaluation_rules.json", scoring_path="scoring_system.json"):
    """Load evaluation rules and scoring system from JSON files"""
    try:
        # Load main evaluation rules
        with open(file_path, "r") as f:
            rules = json.load(f)
        
        # Load scoring system if available
        try:
            with open(scoring_path, "r") as f:
                scoring = json.load(f)
                # Merge scoring system into rules
                rules["scoring_system"] = scoring.get("scoring_system", {})
                
                # Check and standardize scoring scale
                if "score_scale" in rules["scoring_system"]:
                    scale = rules["scoring_system"]["score_scale"]
                    
                    # If scale is 0-10, normalize quality levels to match
                    if scale["max"] == 10:
                        print(f"Detected 0-10 scale in scoring system")
                
        except FileNotFoundError:
            # Require scoring system file
            print(f"Scoring system file '{scoring_path}' not found.")
            return None
            
        return rules
    except FileNotFoundError:
        # Require evaluation rules file
        print(f"Evaluation rules file '{file_path}' not found.")
        return None

def convert_score(score, from_scale, to_scale):
    """
    Convert a score from one scale to another
    
    Args:
        score (float): The score to convert
        from_scale (tuple): The source scale as (min, max)
        to_scale (tuple): The target scale as (min, max)
    
    Returns:
        float: The converted score
    """
    from_min, from_max = from_scale
    to_min, to_max = to_scale
    
    # Ensure score is within source scale bounds
    score = max(from_min, min(score, from_max))
    
    # Convert to percentage within source scale
    percentage = (score - from_min) / (from_max - from_min)
    
    # Apply percentage to target scale
    converted = to_min + percentage * (to_max - to_min)
    
    return converted

# Check for required files
def check_required_files(files_dict):
    """Check if required files exist"""
    missing_files = []
    for file_path, file_desc in files_dict.items():
        if not os.path.exists(file_path):
            missing_files.append(f"{file_desc} ({file_path})")
    
    if missing_files:
        for missing_file in missing_files:
            print(f"Required file not found: {missing_file}")
        return False
    return True

# Flask-specific helper functions
def update_api_keys_from_form(form_data):
    """
    Update API keys from Flask form data and reset clients
    
    Args:
        form_data: Flask request.form data
    """
    try:
        from flask import session
        
        # Update API keys if provided
        anthropic_key = form_data.get('anthropic_key')
        openai_key = form_data.get('openai_key')
        
        if anthropic_key and anthropic_key.strip():
            session['anthropic_key'] = anthropic_key.strip()
            print("Updated Anthropic API key in session")
        
        if openai_key and openai_key.strip():
            session['openai_key'] = openai_key.strip()
            print("Updated OpenAI API key in session")
        
        # Reset clients to force re-initialization with new keys
        reset_api_clients()
        
        return True
    except Exception as e:
        print(f"Error updating API keys: {str(e)}")
        return False

def get_model_provider_from_session():
    """
    Get the current model provider from Flask session with fallback
    
    Returns:
        tuple: (provider_name, model_name)
    """
    try:
        from flask import session
        provider = session.get('provider', 'anthropic')
        
        # Set appropriate model name based on provider
        if provider == 'anthropic':
            model_name = session.get('model_name', 'claude-3-7-sonnet-20250219')
        elif provider == 'openai':
            model_name = session.get('model_name', 'gpt-4o')
        else:
            # Default fallback
            provider = 'anthropic'
            model_name = 'claude-3-7-sonnet-20250219'
        
        return provider, model_name
    except RuntimeError:
        # Outside Flask context, return defaults
        return 'anthropic', 'claude-3-7-sonnet-20250219'
    except Exception as e:
        print(f"Error getting model provider from session: {str(e)}")
        return 'anthropic', 'claude-3-7-sonnet-20250219'