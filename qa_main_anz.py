from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, Response, make_response
import os
import tempfile
import json
from werkzeug.utils import secure_filename
import time
from datetime import datetime
import io
import uuid
from pathlib import Path

# Import your existing modules
from knowledge_base import KnowledgeBase

# UPDATED: Import the new anonymization-enabled modules instead of originals
try:
    from chat_qa_with_anonymization import (
        analyze_chat_transcript,
        EnhancedChatProcessorWithAutoAnonymization as EnhancedChatProcessor,
        analyze_multiple_chats_with_anonymization
    )
    ANONYMIZATION_ENABLED = True
    print("🔒 Auto-anonymization modules loaded successfully")
except ImportError as e:
    print(f"⚠️ Auto-anonymization modules not found, falling back to original: {e}")
    # Fallback to original modules if new ones aren't available
    from chat_qa import analyze_chat_transcript
    from enhanced_chat_processor import EnhancedChatProcessor
    ANONYMIZATION_ENABLED = False

import utils
from utils import detect_language_smart
from chat_anonymizer import ChatAnonymizer

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'bulletproof-dev-key')

# Set up upload folder for temporary files
UPLOAD_FOLDER = tempfile.mkdtemp()
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# Initialize Knowledge Base
kb = KnowledgeBase("qa_knowledge_base.json")

# Load evaluation rules
chat_rules = utils.load_evaluation_rules("evaluation_rules.json", "scoring_system.json")

# ================ BULLETPROOF FILE STORAGE SYSTEM ================
RESULTS_DIR = Path("temp_results")
RESULTS_DIR.mkdir(exist_ok=True)

def save_results_simple(results, analysis_type="batch"):
    """Save results to a simple file and return the filename"""
    try:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{analysis_type}_{timestamp}_{unique_id}.json"
        filepath = RESULTS_DIR / filename
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Saved {analysis_type} results to: {filepath}")
        return filename
    except Exception as e:
        print(f"❌ Error saving results: {e}")
        return None

def load_results_simple(filename):
    """Load results from file"""
    try:
        filepath = RESULTS_DIR / filename
        if not filepath.exists():
            print(f"❌ File not found: {filepath}")
            return None
            
        with open(filepath, 'r', encoding='utf-8') as f:
            results = json.load(f)
        
        print(f"✅ Loaded results from: {filepath}")
        return results
    except Exception as e:
        print(f"❌ Error loading results: {e}")
        return None

# Global variables for current results
current_batch_file = None
current_single_file = None

# ================ HELPER FUNCTIONS ================
def get_api_provider():
    if 'provider' not in session:
        session['provider'] = 'anthropic'
        session['model_name'] = 'claude-3-7-sonnet-20250219'
    return session['provider'], session['model_name']

# ================ AUTHENTICATION ================
@app.before_request
def check_auth():
    if request.endpoint in ('login', 'static'):
        return
    
    if not session.get('authenticated'):
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        password = request.form['password']
        correct_password = os.environ.get('QA_PASSWORD')
        
        if password == correct_password:
            session['authenticated'] = True
            session['login_time'] = time.time()
            return redirect(url_for('index'))
        else:
            error = 'Invalid credentials'
    
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ================ MAIN ROUTES ================
@app.route('/')
def index():
    return render_template('index.html')

# ================ ANONYMIZATION ROUTES (Keep existing for manual use) ================
@app.route('/anonymization', methods=['GET', 'POST'])
def anonymization():
    """Chat anonymization tab - remove sensitive information locally"""
    result = None
    input_text = None
    anonymization_summary = None
    
    if request.method == 'POST':
        print(f"=== ANONYMIZATION POST REQUEST RECEIVED ===")
        print(f"Form keys: {list(request.form.keys())}")
        print(f"Files keys: {list(request.files.keys())}")
        
        try:
            # Initialize anonymizer
            anonymizer = ChatAnonymizer()
            
            # Check if text was pasted
            if 'chat_text' in request.form and request.form['chat_text'].strip():
                input_text = request.form['chat_text']
                print("=== ANONYMIZATION STARTED (Text Input) ===")
                print(f"Text length: {len(input_text)} characters")
                
                # For pasted text, check if it contains multiple chats
                if 'Chat ' in input_text and input_text.count('Chat ') > 1:
                    print("Multiple chats detected in pasted text")
                    result = anonymizer.anonymize_multiple_chats(input_text)
                else:
                    # Single chat
                    result = anonymizer.anonymize_chat_transcript(input_text)
                
                anonymization_summary = anonymizer.get_anonymization_summary(result)
                
                # Store in session for download
                session['last_anonymization'] = result
                
                replacements = result.get('anonymization_report', {}).get('total_replacements', 0)
                chat_count = result.get('chat_count', 1)
                print(f"✅ Anonymized text input: {replacements} replacements across {chat_count} chat(s)")
            
            # Check if file was uploaded
            elif 'anonymization_file' in request.files:
                file = request.files['anonymization_file']
                print(f"File received: {file.filename if file else 'None'}")
                
                if file and file.filename != '':
                    print(f"=== ANONYMIZATION STARTED (File Upload: {file.filename}) ===")
                    
                    try:
                        # Check file size
                        file.seek(0, 2)  # Seek to end
                        file_size = file.tell()
                        file.seek(0)  # Reset to beginning
                        print(f"File size: {file_size} bytes")
                        
                        if file_size > 10 * 1024 * 1024:  # 10MB limit for documents
                            flash('Error: File too large. Maximum size is 10MB.')
                            return render_template('anonymization.html')
                        
                        if file_size == 0:
                            flash('Error: Empty file uploaded.')
                            return render_template('anonymization.html')
                        
                        # Get file extension
                        file_extension = file.filename.lower().split('.')[-1] if '.' in file.filename else ''
                        print(f"File extension: {file_extension}")
                        
                        # Extract text based on file type
                        file_content = None
                        
                        if file_extension == 'docx':
                            # Handle .docx files
                            try:
                                from docx import Document
                                import io
                                
                                # Read the file into memory
                                file_stream = io.BytesIO(file.read())
                                doc = Document(file_stream)
                                
                                # Extract text from all paragraphs
                                paragraphs = []
                                for paragraph in doc.paragraphs:
                                    if paragraph.text.strip():
                                        paragraphs.append(paragraph.text)
                                
                                file_content = '\n'.join(paragraphs)
                                print(f"✅ Successfully extracted text from .docx file ({len(paragraphs)} paragraphs)")
                                
                            except ImportError:
                                flash('Error: python-docx library not installed. Please install it with: pip install python-docx')
                                return render_template('anonymization.html')
                            except Exception as docx_error:
                                print(f"❌ Error reading .docx file: {str(docx_error)}")
                                flash(f'Error reading .docx file: {str(docx_error)}')
                                return render_template('anonymization.html')
                        
                        else:
                            # Handle text files (.txt, .csv, .log)
                            if file_extension not in ['txt', 'csv', 'log', '']:
                                flash(f'Error: Unsupported file type ".{file_extension}". Supported types: .txt, .csv, .log, .docx')
                                return render_template('anonymization.html')
                                
                            # Read file content with multiple encoding attempts
                            encodings_to_try = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
                            
                            for encoding in encodings_to_try:
                                try:
                                    file.seek(0)  # Reset file pointer
                                    file_content = file.read().decode(encoding)
                                    print(f"✅ Successfully decoded file with {encoding}")
                                    break
                                except UnicodeDecodeError as e:
                                    print(f"❌ Failed to decode with {encoding}: {str(e)}")
                                    continue
                        
                        if file_content is None:
                            flash('Error: Unable to read file. Please ensure it\'s a valid text file.')
                            return render_template('anonymization.html')
                        
                        print(f"File content length: {len(file_content)} characters")
                        print(f"First 200 chars: {file_content[:200]}...")
                        
                        # Show preview of original content
                        input_text = file_content[:1000] + "..." if len(file_content) > 1000 else file_content
                        
                        # For uploaded files, always check for multiple chats
                        print("Processing file for multiple chats...")
                        result = anonymizer.anonymize_multiple_chats(file_content)
                        
                        if 'error' in result:
                            print(f"❌ Anonymization error: {result['error']}")
                            flash(f'Error: {result["error"]}')
                            return render_template('anonymization.html')
                        
                        anonymization_summary = anonymizer.get_anonymization_summary(result)
                        
                        # Store in session for download
                        session['last_anonymization'] = result
                        
                        replacements = result.get('anonymization_report', {}).get('total_replacements', 0)
                        chat_count = result.get('chat_count', 1)
                        print(f"✅ Anonymized file: {replacements} replacements across {chat_count} chat(s)")
                        flash(f'Successfully anonymized {file.filename} - Found {chat_count} chats with {replacements} sensitive items')
                        
                    except Exception as file_error:
                        print(f"❌ Error processing file: {str(file_error)}")
                        import traceback
                        print(f"Full traceback: {traceback.format_exc()}")
                        flash(f'Error processing file: {str(file_error)}')
                        return render_template('anonymization.html')
                else:
                    print("❌ No file selected or empty filename")
                    flash('No file selected')
            else:
                print("❌ No input provided")
                flash('Please provide text or upload a file to anonymize')
        
        except Exception as main_error:
            print(f"❌ Main anonymization error: {str(main_error)}")
            import traceback
            print(f"Full traceback: {traceback.format_exc()}")
            flash(f'Anonymization error: {str(main_error)}')
            return render_template('anonymization.html')
    
    print(f"=== RENDERING TEMPLATE ===")
    print(f"Result exists: {result is not None}")
    print(f"Input text length: {len(input_text) if input_text else 0}")
    print(f"Summary exists: {anonymization_summary is not None}")
    
    return render_template(
        'anonymization.html',
        result=result,
        input_text=input_text,
        anonymization_summary=anonymization_summary
    )

@app.route('/download/anonymized/<format>')
def download_anonymized(format):
    """Download anonymized results"""
    print(f"=== DOWNLOAD ANONYMIZED: {format} ===")
    
    if 'last_anonymization' not in session:
        return "No anonymization data available. Please anonymize some content first.", 400
    
    try:
        result = session['last_anonymization']
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        if format == 'txt':
            # Download as plain text file with all chats
            response = make_response(result['anonymized_transcript'])
            response.headers['Content-Type'] = 'text/plain; charset=utf-8'
            
            # Better filename based on whether it's single or multiple chats
            chat_count = result.get('chat_count', 1)
            if chat_count > 1:
                filename = f'anonymized_chats_{chat_count}_{timestamp}.txt'
            else:
                filename = f'anonymized_chat_{timestamp}.txt'
                
            response.headers['Content-Disposition'] = f'attachment; filename={filename}'
            print(f"✅ Returning TXT file: {filename}")
            return response
            
        elif format == 'json':
            # Download as JSON with full report
            json_content = json.dumps(result, indent=2, ensure_ascii=False)
            response = make_response(json_content)
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            
            # Better filename based on whether it's single or multiple chats
            chat_count = result.get('chat_count', 1)
            if chat_count > 1:
                filename = f'anonymized_report_{chat_count}_chats_{timestamp}.json'
            else:
                filename = f'anonymized_report_{timestamp}.json'
                
            response.headers['Content-Disposition'] = f'attachment; filename={filename}'
            print(f"✅ Returning JSON file: {filename}")
            return response
            
        else:
            return f"Unsupported format: {format}. Supported: txt, json", 400
            
    except Exception as e:
        print(f"❌ Download error: {e}")
        import traceback
        print(traceback.format_exc())
        return f"Download failed: {e}", 500

# ================ SINGLE ANALYSIS (UPDATED with auto-anonymization) ================

@app.route('/single-analysis', methods=['GET', 'POST'])
def single_analysis():
    """Single chat analysis with anonymized preview for transparency"""
    global current_single_file
    result = None
    transcript = None
    anonymized_transcript = None
    anonymization_stats = None
    
    if request.method == 'POST':
        transcript = request.form.get('transcript')
        
        if transcript:
            provider, model_name = get_api_provider()
            target_language = request.form.get('target_language', 'en')
            
            print("=== SINGLE ANALYSIS WITH ANONYMIZATION PREVIEW STARTED ===")
            
            try:
                # Step 1: Create anonymizer and get anonymized version for display
                from chat_anonymizer import ChatAnonymizer
                anonymizer = ChatAnonymizer()
                anonymized_transcript, anonymization_report = anonymizer.anonymize_text(transcript)
                
                # Create anonymization stats for display
                anonymization_stats = {
                    'total_replacements': anonymization_report.get('total_replacements', 0),
                    'phone_count': anonymization_report.get('replacements_by_type', {}).get('phone', 0),
                    'email_count': anonymization_report.get('replacements_by_type', {}).get('email', 0),
                    'other_count': max(0, anonymization_report.get('total_replacements', 0) - 
                                 anonymization_report.get('replacements_by_type', {}).get('phone', 0) - 
                                 anonymization_report.get('replacements_by_type', {}).get('email', 0))
                }
                
                print(f"🔒 Anonymization complete: {anonymization_stats['total_replacements']} items removed")
                
                # Step 2: Perform analysis using the anonymization-enabled function if available
                try:
                    # Try to use the anonymization-enabled analysis
                    print("Attempting auto-anonymization analysis...")
                    result = analyze_with_anonymization(
                        transcript,  # Function handles anonymization internally
                        chat_rules,
                        kb,
                        target_language=target_language,
                        prompt_template_path="QA_prompt.md",
                        model_provider=provider,
                        model_name=model_name
                    )
                    print("✅ Used auto-anonymization analysis")
                    
                except NameError:
                    # Fall back to regular analysis with pre-anonymized text
                    print("Auto-anonymization function not available, using standard analysis with pre-anonymized text")
                    from chat_qa import analyze_chat_transcript as original_analyze
                    result = original_analyze(
                        anonymized_transcript,  # Use our pre-anonymized version
                        chat_rules,
                        kb,
                        target_language=target_language,
                        prompt_template_path="QA_prompt.md",
                        model_provider=provider,
                        model_name=model_name
                    )
                    print("✅ Used standard analysis with anonymized text")
                
                # Store result in file
                if result:
                    # Add anonymization info to result for potential future use
                    result['anonymization_info'] = {
                        'was_anonymized': True,
                        'total_replacements': anonymization_stats['total_replacements'],
                        'replacement_types': anonymization_report.get('replacements_by_type', {})
                    }
                    
                    current_single_file = save_results_simple(result, "single")
                    print(f"✅ Stored single result in file: {current_single_file}")
                else:
                    print("❌ No result to store")
                    
            except Exception as e:
                print(f"❌ Error during analysis: {str(e)}")
                import traceback
                print(traceback.format_exc())
                flash(f'Analysis error: {str(e)}')
                # Reset variables on error
                result = None
                anonymized_transcript = None
                anonymization_stats = None
    
    # Language detection
    detected_language = None
    if transcript:
        try:
            provider, _ = get_api_provider()
            lang_code, detected_language = detect_language_smart(transcript, provider)
            print(f"Detected language: {detected_language} (code: {lang_code})")
        except Exception as lang_error:
            print(f"Language detection error: {str(lang_error)}")
            detected_language = "English (fallback)"
    
    return render_template(
        'single_analysis.html', 
        result=result, 
        transcript=transcript,
        anonymized_transcript=anonymized_transcript,
        anonymization_stats=anonymization_stats,
        detected_language=detected_language,
        categories=chat_rules.get('categories', [])
    )

# ================ BATCH ANALYSIS (UPDATED with auto-anonymization) ================
@app.route('/batch-analysis', methods=['GET', 'POST'])
def batch_analysis():
    """Batch chat analysis - now with auto-anonymization if enabled"""
    global current_batch_file
    results = []
    processor = EnhancedChatProcessor()  # This may auto-anonymize if enabled
    
    if request.method == 'POST':
        if ANONYMIZATION_ENABLED:
            print("=== BATCH ANALYSIS WITH AUTO-ANONYMIZATION STARTED ===")
        else:
            print("=== BATCH ANALYSIS (NO ANONYMIZATION) STARTED ===")
        
        # Check if files were uploaded
        if 'batch_files' not in request.files:
            print("❌ No 'batch_files' in request.files")
            flash('No files selected')
            return redirect(request.url)
        
        files = request.files.getlist('batch_files')
        print(f"✅ Found {len(files)} files in request")
        
        # Filter out empty file selections
        valid_files = [f for f in files if f and f.filename != '']
        
        if not valid_files:
            flash('No valid files selected')
            return redirect(request.url)
        
        print(f"✅ Processing {len(valid_files)} valid files")
        
        # Process each file (anonymization happens automatically if enabled)
        all_chats = []
        
        for file in valid_files:
            try:
                print(f"Processing file: {file.filename}")
                
                file_bytes = file.read()
                file_obj = io.BytesIO(file_bytes)
                file_obj.name = file.filename
                file_obj.seek(0)
                
                # This automatically anonymizes if the enhanced processor supports it
                chats = processor.extract_chats_from_file(file_obj)
                
                if chats:
                    print(f"✅ Extracted {len(chats)} chats from {file.filename}")
                    all_chats.extend(chats)
                else:
                    print(f"❌ No chats found in {file.filename}")
                    flash(f"No valid chat transcripts found in {file.filename}")
                    
            except Exception as e:
                print(f"❌ Error processing {file.filename}: {str(e)}")
                flash(f"Error processing {file.filename}: {str(e)}")
        
        # Process batch analysis if chats were found
        if all_chats:
            print(f"✅ Starting analysis of {len(all_chats)} chats")
            provider, model_name = get_api_provider()
            target_language = request.form.get('target_language', 'en')
            
            if ANONYMIZATION_ENABLED and 'analyze_multiple_chats_with_anonymization' in globals():
                # Use the batch anonymization function
                results = analyze_multiple_chats_with_anonymization(
                    all_chats,
                    chat_rules,
                    kb,
                    target_language=target_language,
                    prompt_template_path="QA_prompt.md",
                    model_provider=provider,
                    model_name=model_name
                )
            else:
                # Use regular batch processing
                successful_analyses = 0
                failed_analyses = 0
                
                for i, chat in enumerate(all_chats):
                    try:
                        # Check if chat content is valid
                        if not chat.get('processed_content') or len(chat.get('processed_content', '').strip()) < 50:
                            print(f"❌ Skipping chat {chat.get('id')}: Invalid or too short content")
                            failed_analyses += 1
                            continue
                        
                        print(f"✅ Analyzing chat {i+1}/{len(all_chats)}: {chat.get('id')}")
                        
                        # Analyze the chat
                        result = analyze_chat_transcript(
                            chat['processed_content'],
                            chat_rules,
                            kb,
                            target_language=target_language,
                            prompt_template_path="QA_prompt.md",
                            model_provider=provider,
                            model_name=model_name
                        )
                        
                        if result:
                            # Validate and fix score
                            if 'weighted_overall_score' not in result or result['weighted_overall_score'] is None:
                                # Calculate score manually
                                total_weight = sum(param["weight"] for param in chat_rules["parameters"])
                                weighted_score = 0
                                valid_params = 0
                                
                                for param in chat_rules["parameters"]:
                                    param_name = param["name"]
                                    if param_name in result and isinstance(result[param_name], dict):
                                        score_value = result[param_name].get("score")
                                        if isinstance(score_value, (int, float)):
                                            weighted_score += score_value * param["weight"]
                                            valid_params += 1
                                
                                if total_weight > 0 and valid_params > 0:
                                    result["weighted_overall_score"] = round(weighted_score / total_weight, 2)
                                else:
                                    result["weighted_overall_score"] = 0
                            
                            # Ensure score is valid
                            try:
                                score = float(result.get('weighted_overall_score', 0))
                                result['weighted_overall_score'] = round(score, 2)
                            except (ValueError, TypeError):
                                result['weighted_overall_score'] = 0
                            
                            # Add metadata
                            result['chat_id'] = chat['id']
                            result['content_preview'] = chat['content'][:500] + "..." if len(chat['content']) > 500 else chat['content']
                            
                            results.append(result)
                            successful_analyses += 1
                            print(f"✅ Added result to list. Total results: {len(results)}")
                            
                        else:
                            print(f"❌ No analysis result for chat {chat.get('id')}")
                            failed_analyses += 1
                            
                    except Exception as e:
                        print(f"❌ Error analyzing chat {chat.get('id')}: {str(e)}")
                        failed_analyses += 1
            
            # Add language detection to results
            for result in results:
                try:
                    # Find the original chat for language detection
                    original_chat = next((chat for chat in all_chats if chat.get('id') == result.get('chat_id')), None)
                    if original_chat:
                        lang_code, lang_name = detect_language_smart(original_chat.get('processed_content', ''), provider)
                        result['detected_language'] = lang_name
                    else:
                        result['detected_language'] = 'English (fallback)'
                except Exception as lang_error:
                    print(f"Language detection error: {str(lang_error)}")
                    result['detected_language'] = 'English (fallback)'
            
            # Store results in file
            if results:
                print(f"=== STORING {len(results)} RESULTS ===")
                current_batch_file = save_results_simple(results, "batch")
                
                if current_batch_file:
                    print(f"✅ Stored batch results in file: {current_batch_file}")
                    privacy_msg = " with automatic privacy protection" if ANONYMIZATION_ENABLED else ""
                    flash(f'Successfully analyzed {len(results)} chats{privacy_msg}.')
                else:
                    print("❌ Failed to store batch results")
                    flash('Analysis completed but results could not be saved for download.')
            else:
                print("❌ NO RESULTS TO STORE")
                flash('No analysis results were generated.')
                
        else:
            flash('No chat transcripts were found in the uploaded files.')
    
    return render_template(
        'batch_analysis.html',
        results=results,
        categories=chat_rules.get('categories', []),
        anonymization_enabled=ANONYMIZATION_ENABLED
    )

# ================ KNOWLEDGE BASE ================
@app.route('/knowledge-base', methods=['GET', 'POST'])
def knowledge_base():
    categories = kb.get_all_categories()
    selected_category = request.args.get('category', 'All Categories')
    
    if selected_category == 'All Categories':
        qa_pairs = kb.qa_pairs.get('qa_pairs', [])
    else:
        qa_pairs = kb.get_qa_pairs_by_category(selected_category)
    
    return render_template(
        'knowledge_base.html', 
        qa_pairs=qa_pairs,
        categories=categories,
        selected_category=selected_category
    )

# ================ SETTINGS ================
@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        provider = request.form.get('provider')
        if provider in ['anthropic', 'openai']:
            session['provider'] = provider
            
            if provider == 'anthropic':
                session['model_name'] = 'claude-3-7-sonnet-20250219'
            else:
                session['model_name'] = 'gpt-4o'
        
        anthropic_key = request.form.get('anthropic_key')
        openai_key = request.form.get('openai_key')
        
        if anthropic_key:
            session['anthropic_key'] = anthropic_key
        
        if openai_key:
            session['openai_key'] = openai_key
            
        flash('Settings updated successfully')
        
    return render_template(
        'settings.html',
        provider=session.get('provider', 'anthropic'),
        has_anthropic_key='anthropic_key' in session,
        has_openai_key='openai_key' in session,
        anonymization_enabled=ANONYMIZATION_ENABLED
    )

# ================ DOWNLOAD SYSTEM ================
@app.route('/download/<type>/<format>')
def download_report(type, format):
    """Download analysis reports"""
    print(f"=== DOWNLOAD REQUEST: {type}/{format} ===")
    
    try:
        global current_batch_file, current_single_file
        
        if type == 'batch' and format == 'csv':
            print(f"Current batch file: {current_batch_file}")
            
            if not current_batch_file:
                return "No batch analysis data available. Please run batch analysis first.", 400
            
            # Load results from file
            results = load_results_simple(current_batch_file)
            if not results:
                return "Batch analysis data expired or corrupted. Please run batch analysis again.", 400
            
            print(f"✅ Loaded {len(results)} results for download")
            
            # Create comprehensive CSV
            csv_lines = []
            csv_lines.append("Chat ID,Overall Score,Quality Level,Language,Parameter,Score,Explanation,Example,Suggestion")
            
            for result in results:
                chat_id = result.get('chat_id', 'Unknown')
                overall_score = result.get('weighted_overall_score', 0)
                language = result.get('detected_language', 'Unknown')
                
                # Determine quality level
                if overall_score >= 85:
                    quality_level = "Excellent"
                elif overall_score >= 70:
                    quality_level = "Good"
                elif overall_score >= 50:
                    quality_level = "Needs Improvement"
                else:
                    quality_level = "Poor"
                
                # Add row for each parameter
                for param in chat_rules["parameters"]:
                    param_name = param["name"]
                    
                    if param_name in result and isinstance(result[param_name], dict):
                        param_data = result[param_name]
                        score = param_data.get("score", "N/A")
                        explanation = str(param_data.get("explanation", "")).replace('"', "'")[:200]
                        example = str(param_data.get("example", "")).replace('"', "'")[:200]
                        suggestion = str(param_data.get("suggestion", "")).replace('"', "'")[:200]
                    else:
                        score = "N/A"
                        explanation = "No analysis available"
                        example = "N/A"
                        suggestion = "N/A"
                    
                    csv_lines.append(f'"{chat_id}",{overall_score:.2f},"{quality_level}","{language}","{param_name}",{score},"{explanation}","{example}","{suggestion}"')
            
            csv_content = '\n'.join(csv_lines)
            
            # Create response
            response = make_response(csv_content)
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            
            # Add privacy indicator to filename if anonymization was used
            privacy_suffix = "_secure" if ANONYMIZATION_ENABLED else ""
            response.headers['Content-Disposition'] = f'attachment; filename=qa_batch_analysis{privacy_suffix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            
            print(f"✅ Returning CSV with {len(csv_lines)} rows")
            return response
            
        elif type == 'single' and format == 'json':
            print(f"Current single file: {current_single_file}")
            
            if not current_single_file:
                return "No single analysis data available. Please run single analysis first.", 400
            
            # Load result from file
            result = load_results_simple(current_single_file)
            if not result:
                return "Single analysis data expired or corrupted. Please run analysis again.", 400
            
            json_content = json.dumps(result, indent=2, ensure_ascii=False)
            
            response = make_response(json_content)
            response.headers['Content-Type'] = 'application/json; charset=utf-8'
            
            # Add privacy indicator to filename if anonymization was used
            privacy_suffix = "_secure" if ANONYMIZATION_ENABLED else ""
            response.headers['Content-Disposition'] = f'attachment; filename=qa_single_analysis{privacy_suffix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            
            return response
            
        elif type == 'single' and format == 'csv':
            print(f"Current single file: {current_single_file}")
            
            if not current_single_file:
                return "No single analysis data available. Please run single analysis first.", 400
            
            # Load result from file
            result = load_results_simple(current_single_file)
            if not result:
                return "Single analysis data expired or corrupted. Please run analysis again.", 400
            
            csv_lines = ["Parameter,Score,Explanation,Example,Suggestion"]
            
            for param in chat_rules["parameters"]:
                param_name = param["name"]
                if param_name in result and isinstance(result[param_name], dict):
                    param_data = result[param_name]
                    score = param_data.get("score", "N/A")
                    explanation = str(param_data.get("explanation", "")).replace('"', "'")[:200]
                    example = str(param_data.get("example", "")).replace('"', "'")[:200]
                    suggestion = str(param_data.get("suggestion", "")).replace('"', "'")[:200]
                    csv_lines.append(f'"{param_name}",{score},"{explanation}","{example}","{suggestion}"')
            
            csv_content = '\n'.join(csv_lines)
            
            response = make_response(csv_content)
            response.headers['Content-Type'] = 'text/csv; charset=utf-8'
            
            # Add privacy indicator to filename if anonymization was used
            privacy_suffix = "_secure" if ANONYMIZATION_ENABLED else ""
            response.headers['Content-Disposition'] = f'attachment; filename=qa_single_analysis{privacy_suffix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            
            return response
        
        else:
            return f"Unsupported download: {type}/{format}", 400
            
    except Exception as e:
        print(f"❌ Download error: {e}")
        import traceback
        print(traceback.format_exc())
        return f"Download failed: {e}", 500

# ================ DEBUG AND UTILITY ROUTES ================
@app.route('/debug/files')
def debug_files():
    """Debug route to check current files"""
    if not session.get('authenticated'):
        return "Not authenticated", 401
    
    global current_batch_file, current_single_file
    
    file_info = {
        'current_batch_file': current_batch_file,
        'current_single_file': current_single_file,
        'batch_file_exists': current_batch_file and (RESULTS_DIR / current_batch_file).exists() if current_batch_file else False,
        'single_file_exists': current_single_file and (RESULTS_DIR / current_single_file).exists() if current_single_file else False,
        'total_result_files': len(list(RESULTS_DIR.glob('*.json'))),
        'result_files': [f.name for f in RESULTS_DIR.glob('*.json')],
        'anonymization_enabled': ANONYMIZATION_ENABLED
    }
    
    return jsonify(file_info)

@app.route('/cleanup-temp-files')
def cleanup_temp_files():
    """Clean up old result files"""
    if not session.get('authenticated'):
        return "Not authenticated", 401
    
    try:
        count = 0
        for file_path in RESULTS_DIR.glob('*.json'):
            # Delete files older than 1 hour
            if (datetime.now() - datetime.fromtimestamp(file_path.stat().st_mtime)).seconds > 3600:
                file_path.unlink()
                count += 1
        
        return f"Cleaned up {count} old files"
    except Exception as e:
        return f"Cleanup error: {e}"

# ================ ANONYMIZATION STATUS ROUTE ================
@app.route('/anonymization-status')
def anonymization_status():
    """Show current anonymization status"""
    status = {
        'auto_anonymization_enabled': ANONYMIZATION_ENABLED,
        'version': '1.0',
        'description': 'Automatic data anonymization before LLM processing' if ANONYMIZATION_ENABLED else 'Manual anonymization available',
        'protected_data_types': [
            'Phone numbers (+1-555-123-4567 → +XX-XXX-XXX-0001)',
            'Email addresses (john@test.com → user1@anonymized.com)',
            'Credit card numbers (4111-1111-1111-1111 → XXXX-XXXX-XXXX-0001)',
            'Bank account numbers (123456789 → ACCT000000000001)',
            'ID/Passport numbers (A1234567 → IDA1B2C3D4)',
            'OTP codes (123456 → XX0001)',
            'Dates of birth (01/01/1990 → XX/XX/1925)',
            'Crypto wallet addresses',
            'Transaction IDs and hashes'
        ] if ANONYMIZATION_ENABLED else [],
        'preserved_identifiers': [
            'Chat numbers (Chat 01234567 → preserved)',
            'Session IDs',
            'Ticket numbers',
            'Case references',
            'Order numbers'
        ] if ANONYMIZATION_ENABLED else [],
        'process': [
            '1. User uploads chat files',
            '2. System extracts individual chats',
            '3. 🔒 Auto-anonymization removes sensitive data',
            '4. Clean data sent to AI for analysis',
            '5. Normal QA results returned to user',
            '6. User never sees anonymized version'
        ] if ANONYMIZATION_ENABLED else [
            '1. User uploads chat files',
            '2. System extracts individual chats', 
            '3. Original data sent to AI for analysis',
            '4. QA results returned to user',
            '5. Manual anonymization available in separate tab'
        ]
    }
    
    return jsonify(status)

# ================ CONTEXT PROCESSOR ================
@app.context_processor
def utility_processor():
    def get_api_key(provider):
        if provider == 'anthropic' and 'anthropic_key' in session:
            return session['anthropic_key']
        elif provider == 'openai' and 'openai_key' in session:
            return session['openai_key']
        return os.environ.get(f'{provider.upper()}_API_KEY')
    
    def anonymization_enabled():
        return ANONYMIZATION_ENABLED
    
    return dict(get_api_key=get_api_key, anonymization_enabled=anonymization_enabled)

# ================ MAIN ================
if __name__ == '__main__':
    if ANONYMIZATION_ENABLED:
        print("🚀 Starting QA Engine with Auto-Anonymization")
        print("🔒 Auto-anonymization: ENABLED")
        print("   - Phone numbers, emails, credit cards will be automatically removed")
        print("   - Chat numbers and system IDs will be preserved")
        print("   - Users will never see anonymized data")
    else:
        print("🚀 Starting QA Engine (Standard Mode)")
        print("ℹ️ Auto-anonymization: DISABLED")
        print("   - Manual anonymization available in separate tab")
        print("   - To enable auto-anonymization, ensure chat_qa_with_anonymization.py is available")
    
    print(f"📁 Results directory: {RESULTS_DIR.absolute()}")
    
    app.run(debug=os.environ.get('FLASK_DEBUG', 'False') == 'True', port=5001)
