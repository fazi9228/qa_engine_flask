import re
import io
import os
import hashlib
import datetime
from typing import List, Dict, Any, Optional
import time
import tempfile
import glob

# Try to import file handling libraries
try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import PyPDF2
except ImportError:
    PyPDF2 = None

try:
    import docx
except ImportError:
    docx = None

class EnhancedChatProcessor:
    """Enhanced processor for extracting and parsing chat transcripts from various file formats"""

    def extract_chats_from_file(self, uploaded_file):
        """
        Extract chats from uploaded file based on file type
        
        Args:
        uploaded_file: The uploaded file object (BytesIO with .name attribute or file-like object)
        
        Returns:
        List of chat dictionaries
        """
        try:
            # Handle both file path strings and file objects
            if hasattr(uploaded_file, 'name'):
                filename = uploaded_file.name
            elif hasattr(uploaded_file, 'filename'):
                filename = uploaded_file.filename
            else:
                raise ValueError("File object must have 'name' or 'filename' attribute")
                
            file_extension = filename.split('.')[-1].lower()
            print(f"Processing file: {filename}, Type: {file_extension}")
            
            # Always reset file pointer to beginning
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
            
            if file_extension == 'txt':
                return self._extract_from_txt(uploaded_file)
            elif file_extension == 'csv':
                if pd is None:
                    raise ImportError("pandas library is required for CSV processing. Install with: pip install pandas")
                return self._extract_from_csv(uploaded_file)
            elif file_extension == 'pdf':
                if PyPDF2 is None:
                    raise ImportError("PyPDF2 library is required for PDF processing. Install with: pip install PyPDF2")
                return self._extract_from_pdf(uploaded_file)
            elif file_extension == 'docx':
                if docx is None:
                    raise ImportError("python-docx library is required for DOCX processing. Install with: pip install python-docx")
                return self._extract_from_docx(uploaded_file)
            else:
                raise ValueError(f"Unsupported file format: {file_extension}")
        except Exception as e:
            import traceback
            print(f"Error in extract_chats_from_file: {str(e)}")
            print(traceback.format_exc())
            return []

    def _extract_from_txt(self, uploaded_file):
        """Extract chats from a text file"""
        try:
            # Reset file pointer to beginning
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
            
            # Handle different file object types
            if hasattr(uploaded_file, 'read'):
                # For BytesIO objects or file-like objects
                content_bytes = uploaded_file.read()
                if isinstance(content_bytes, bytes):
                    content = content_bytes.decode('utf-8')
                else:
                    content = content_bytes
            else:
                raise ValueError("File object must have a 'read' method")
                
            return self._split_text_into_chats(content)
        except Exception as e:
            print(f"Error extracting from TXT: {str(e)}")
            return []

    def _extract_from_csv(self, uploaded_file):
        """Extract chats from a CSV file"""
        try:
            # Reset file pointer to beginning
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
            
            # Read CSV into pandas DataFrame
            # Handle both BytesIO and file-like objects
            if hasattr(uploaded_file, 'getvalue'):
                # For BytesIO objects
                csv_content = uploaded_file.getvalue()
                if isinstance(csv_content, bytes):
                    csv_content = csv_content.decode('utf-8')
                df = pd.read_csv(io.StringIO(csv_content))
            else:
                # For other file-like objects
                df = pd.read_csv(uploaded_file)

            # Check for common columns that might contain chat content
            content_columns = [col for col in df.columns if any(
                term in col.lower() for term in ['chat', 'message', 'content', 'text', 'transcript']
            )]

            if not content_columns:
                # If no obvious content column, use the first column containing text data
                for col in df.columns:
                    if df[col].dtype == 'object':
                        content_columns = [col]
                        break

            # If still no content column found, use all columns
            if not content_columns:
                print("Warning: Couldn't identify chat content columns. Using all columns.")
                content_columns = df.columns.tolist()

            # Join all content into a single string
            content = ""

            if len(content_columns) == 1:
                # Use entire CSV as one chat
                main_col = content_columns[0]
                content = "\n".join(df[main_col].astype(str).tolist())
            else:
                # Try to format as a dialogue
                for _, row in df.iterrows():
                    for col in content_columns:
                        content += f"{col}: {row[col]}\n"
                    content += "\n"

            return self._split_text_into_chats(content)

        except Exception as e:
            print(f"Error extracting from CSV: {str(e)}")
            return []
    
    def _extract_from_pdf(self, uploaded_file):
        """Extract chats from a PDF file"""
        try:
            # Reset file pointer to beginning
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
            
            # Handle different file object types
            if hasattr(uploaded_file, 'getvalue'):
                # For BytesIO objects
                pdf_data = uploaded_file.getvalue()
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_data))
            else:
                # For other file-like objects
                pdf_reader = PyPDF2.PdfReader(uploaded_file)
                
            content = ""

            # Extract text from all pages
            for page_num in range(len(pdf_reader.pages)):
                content += pdf_reader.pages[page_num].extract_text() + "\n\n"
                
            return self._split_text_into_chats(content)
            
        except Exception as e:
            print(f"Error extracting from PDF: {str(e)}")
            return []

    def _extract_from_docx(self, uploaded_file):
        """Extract chats from a DOCX file"""
        try:
            # Reset file pointer to beginning
            if hasattr(uploaded_file, 'seek'):
                uploaded_file.seek(0)
            
            # Handle different file object types
            if hasattr(uploaded_file, 'getvalue'):
                # For BytesIO objects
                docx_data = uploaded_file.getvalue()
                doc = docx.Document(io.BytesIO(docx_data))
            else:
                # For other file-like objects
                doc = docx.Document(uploaded_file)
            
            # Process paragraphs with better structure preservation
            content_lines = []
            current_line = ""
            
            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:  # Empty paragraph
                    if current_line:
                        content_lines.append(current_line)
                        current_line = ""
                    content_lines.append("")  # Preserve empty lines for structure
                    continue
                    
                # Check if this is a continuation of the previous line
                if text.startswith((':', '-', '...')) and current_line:
                    current_line += text
                else:
                    if current_line:
                        content_lines.append(current_line)
                    current_line = text
            
            # Add the last line if any
            if current_line:
                content_lines.append(current_line)
                
            # Join lines with proper spacing    
            content = "\n".join(content_lines)
            
            # Process the content
            chats = self._split_text_into_chats(content)
            
            # Add debug info about extracted chats
            if not chats:
                print("Warning: No chats were extracted. Content may not match expected format.")
                print("Content preview:")
                print(content[:500])  # Show first 500 chars
                
            return chats
            
        except Exception as e:
            print(f"Error extracting from DOCX: {str(e)}")
            return []

    def _extract_conversation_id_and_type(self, header_text: str) -> tuple[Optional[str], str]:
        """
        Extract conversation ID and determine if it's a Chat or Case.
        Returns: (conversation_id, conversation_type)
        """
        # Chat patterns
        chat_patterns = [
            r"Chat\s*#?\s*(\d+)",                    # "Chat 01331292" or "Chat #01331292"
            r"Chat\s*:\s*(\d+)",                     # "Chat : 01331292"
            r"Chat\s+ID\s*:?\s*(\d+)",              # "Chat ID: 01331292"
            r"[A-Z]{2,}\s*[:-]?\s*Chat\s*#?\s*(\d+)",  # "TH: Chat 01331292"
        ]
        
        # Case patterns
        case_patterns = [
            r"Case\s+ID\s+CT(\d+)",                  # "Case ID CT70707"
            r"Case\s+(\d+)",                         # "Case 55254523"
            r"Case\s*#\s*(\d+)",                     # "Case #55254523"
            r"Case\s*:\s*(\d+)",                     # "Case : 55254523"
        ]
        
        # Check for Chat patterns
        for pattern in chat_patterns:
            match = re.search(pattern, header_text, re.IGNORECASE)
            if match:
                chat_id = match.group(1)
                
                # Handle duplicated numbers
                if len(chat_id) >= 16:
                    half_len = len(chat_id) // 2
                    if chat_id[:half_len] == chat_id[half_len:2*half_len]:
                        chat_id = chat_id[:half_len]
                
                return f"Chat_{chat_id}", "chat"
        
        # Check for Case patterns
        for pattern in case_patterns:
            match = re.search(pattern, header_text, re.IGNORECASE)
            if match:
                case_id = match.group(1)
                
                # Handle duplicated numbers
                if len(case_id) >= 16:
                    half_len = len(case_id) // 2
                    if case_id[:half_len] == case_id[half_len:2*half_len]:
                        case_id = case_id[:half_len]
                
                return f"Case_{case_id}", "case"
        
        # If no match found, generate a hash
        hash_obj = hashlib.md5(header_text.encode())
        return f"Unknown_{hash_obj.hexdigest()[:8]}", "unknown"
    
    def _split_text_into_chats(self, text: str) -> List[Dict[str, Any]]:
        """
        Split a text containing multiple chat/case transcripts into individual conversations.
        Now supports both Chat and Case formats.
        """
        conversations = []
        
        # Define minimum content requirements
        MIN_LINES = 3
        MIN_CHARS = 50
        
        # UPDATED: Support both Chat and Case formats
        conversation_start_patterns = [
            # Chat patterns
            r"(?:^|\n)\s*Chat\s*#?\s*(\d+)",                    # "Chat 01331292" or "Chat #01331292"
            r"(?:^|\n)\s*Chat\s*:\s*(\d+)",                     # "Chat : 01331292"
            r"(?:^|\n)\s*Chat\s+ID\s*:?\s*(\d+)",              # "Chat ID: 01331292"
            r"(?:^|\n)[A-Z]{2,}\s*[:-]?\s*Chat\s*#?\s*(\d+)",  # "TH: Chat 01331292"
            
            # Case patterns (NEW)
            r"(?:^|\n)\s*Case\s+ID\s+CT(\d+)",                  # "Case ID CT70707"
            r"(?:^|\n)\s*Case\s+(\d+)",                         # "Case 55254523"
            r"(?:^|\n)\s*Case\s*#\s*(\d+)",                     # "Case #55254523"
            r"(?:^|\n)\s*Case\s*:\s*(\d+)",                     # "Case : 55254523"
        ]
        
        # Create combined pattern
        combined_pattern = '|'.join(f"(?:{pattern})" for pattern in conversation_start_patterns)
        
        print(f"DEBUG: Looking for Chat/Case patterns in text")
        print(f"DEBUG: Text length: {len(text)} characters")
        print(f"DEBUG: First 300 chars: {text[:300]}")
        
        # Find all conversation headers
        matches = list(re.finditer(combined_pattern, text, re.IGNORECASE | re.MULTILINE))
        
        print(f"DEBUG: Found {len(matches)} conversation headers")
        for i, match in enumerate(matches):
            header_text = match.group().strip()
            print(f"DEBUG: Match {i+1}: '{header_text}' at position {match.start()}-{match.end()}")
        
        if not matches:
            print("DEBUG: No conversation headers found, treating entire text as single conversation")
            # If no headers found, treat entire text as one conversation
            processed_content = self._clean_and_process_chat(text)
            if processed_content and len(processed_content.strip()) >= MIN_CHARS:
                conversations.append({
                    'id': 'Conversation_Single',
                    'type': 'unknown',
                    'content': text,
                    'timestamp': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'processed_content': processed_content
                })
            return conversations
        
        # Extract conversation content between matches
        for i, match in enumerate(matches):
            start_pos = match.start()
            
            # Determine end position
            if i + 1 < len(matches):
                end_pos = matches[i + 1].start()
            else:
                end_pos = len(text)
            
            # Extract conversation content
            conversation_content = text[start_pos:end_pos].strip()
            
            print(f"DEBUG: Processing conversation {i+1}")
            print(f"DEBUG: Content length: {len(conversation_content)}")
            print(f"DEBUG: First 100 chars: {conversation_content[:100]}...")
            
            # Check if conversation meets minimum requirements
            lines = [line for line in conversation_content.split('\n') if line.strip()]
            if len(lines) >= MIN_LINES and len(conversation_content.strip()) >= MIN_CHARS:
                
                # Extract conversation ID and determine type
                conversation_id, conversation_type = self._extract_conversation_id_and_type(match.group().strip())
                
                if not conversation_id:
                    conversation_id = f"{conversation_type.title()}_{i+1}"
                
                # Extract timestamp and process content
                timestamp = self._extract_timestamp(conversation_content)
                processed_content = self._clean_and_process_chat(conversation_content)
                
                print(f"DEBUG: Conversation ID: {conversation_id}, Type: {conversation_type}")
                print(f"DEBUG: Processed content length: {len(processed_content) if processed_content else 0}")
                
                if processed_content:
                    conversations.append({
                        'id': conversation_id,
                        'type': conversation_type,
                        'content': conversation_content,
                        'timestamp': timestamp or datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'processed_content': processed_content
                    })
                    print(f"DEBUG: Successfully added {conversation_type} {conversation_id}")
                else:
                    print(f"DEBUG: Skipped {conversation_type} {conversation_id} - no valid processed content")
            else:
                print(f"DEBUG: Skipped conversation {i+1} - insufficient content ({len(lines)} lines, {len(conversation_content)} chars)")
        
        print(f"DEBUG: Final result: {len(conversations)} conversations extracted")
        return conversations

    def _extract_chat_id(self, chat_text: str) -> Optional[str]:
        """Extract chat/case ID from text - Updated for backward compatibility."""
        conversation_id, _ = self._extract_conversation_id_and_type(chat_text)
        return conversation_id

    def _extract_timestamp(self, chat_text: str) -> Optional[str]:
        """Extract timestamp from chat text."""
        timestamp_patterns = [
            r"Chat Started:\s*([^,\n]+(?:\s+\d{4})?)",
            r"Session Started:\s*([^,\n]+(?:\s+\d{4})?)",
            r"Conversation Started:\s*([^,\n]+(?:\s+\d{4})?)"
        ]

        for pattern in timestamp_patterns:
            match = re.search(pattern, chat_text, re.IGNORECASE)
            if match:
                try:
                    timestamp_str = match.group(1).strip()
                    # Try to parse the timestamp - handle various formats
                    for fmt in [
                        "%A, %B %d, %Y, %H:%M:%S",
                        "%A, %B %d, %Y %H:%M:%S",
                        "%Y-%m-%d %H:%M:%S"
                    ]:
                        try:
                            parsed_time = datetime.datetime.strptime(timestamp_str, fmt)
                            return parsed_time.strftime("%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            continue
                except Exception:
                    pass
        return None

    def _clean_and_process_chat(self, chat_text: str) -> str:
        """Clean and format chat content for analysis - Enhanced version."""
        lines = chat_text.split('\n')
        processed_lines = []
        has_valid_content = False
        
        # Enhanced speaker patterns to handle your specific format
        speaker_patterns = {
            'customer': [
                r'^(?:Customer|Client|Visitor|User|Guest|[A-Z][a-z]+\s+[A-Z][a-z]+)',  # Names like "Chollasin Lawpiboolpipat"
                r'^\(\d+[ms]\)\s*(?:Customer|Client|Visitor|User|Guest)',
                r'^.*?(?:Customer|Client|Visitor|User|Guest)\s*:',
                r'^\d{2}/\d{2}/\d{4}\s+\d{1,2}:\d{2}\s+[ap]m\s*$',  # Timestamp lines
            ],
            'agent': [
                r'^(?:Agent|Support|Assistant|Representative|Bot|Chatbot|Pepper|Mae\s+T|System)',
                r'^\(\d+[ms]\)\s*(?:Agent|Support|Assistant|Representative|Bot|Chatbot|Pepper)',
                r'^.*?(?:Agent|Support|Assistant|Representative|Bot|Chatbot|Pepper)\s*:',
                r'^[A-Z]\s*$',  # Single letter lines like "S"
            ]
        }

        # Skip patterns - only skip true non-conversation content
        skip_patterns = [
            r'^\s*\{ChatWindowButton:',
            r'^\s*Page \d+ of \d+',
            r'^\s*Report generated',
            r'^\s*[-=*_]{3,}\s*$',  # Separator lines like *************
            r'^\s*Chat\s*#?\s*\d+\s*$',  # Chat header lines
            r'^\s*Chat Started:',
            r'^\s*This chat conversation was',
            r'^\s*Thursday \d+ June\s*$',
            r'^\s*Monday \d+ June\s*$',
        ]

        skip_pattern = '|'.join(skip_patterns)
        has_conversation = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Skip non-conversation content
            if re.match(skip_pattern, line, re.IGNORECASE):
                continue

            # Check for any type of message
            is_message = False
            original_line = line
            
            # Check for customer messages (including names)
            for pattern in speaker_patterns['customer']:
                if re.match(pattern, line, re.IGNORECASE):
                    is_message = True
                    has_valid_content = True
                    has_conversation = True
                    
                    # Clean up the line but preserve speaker identity
                    line = re.sub(r'^\(\d+[ms]\)\s*', '', line)  # Remove timestamp
                    
                    # If it's a name pattern, keep the name
                    if re.match(r'^[A-Z][a-z]+\s+[A-Z][a-z]+', line):
                        # It's a customer name - keep as is
                        pass
                    else:
                        # Standard customer pattern
                        line = re.sub(r'^.*?(?:Customer|Client|Visitor|User|Guest)\s*:', 'Customer:', line, flags=re.IGNORECASE)
                    break

            # Check for agent/bot messages
            if not is_message:
                for pattern in speaker_patterns['agent']:
                    if re.match(pattern, line, re.IGNORECASE):
                        is_message = True
                        has_valid_content = True
                        has_conversation = True
                        
                        # Clean up the line
                        line = re.sub(r'^\(\d+[ms]\)\s*', '', line)  # Remove timestamp
                        
                        # Preserve specific agent names like "Mae T"
                        if re.match(r'^Mae\s+T', line, re.IGNORECASE):
                            line = re.sub(r'^Mae\s+T\s*', 'Mae T: ', line, flags=re.IGNORECASE)
                        elif re.match(r'^System', line, re.IGNORECASE):
                            line = re.sub(r'^System\s*', 'System: ', line, flags=re.IGNORECASE)
                        elif re.match(r'^[A-Z]\s*$', line):
                            line = 'System: ' + line  # Single letters become system messages
                        else:
                            # Generic agent pattern
                            line = re.sub(r'^.*?(?:Agent|Support|Assistant|Representative)\s*:', 'Agent:', line, flags=re.IGNORECASE)
                        break

            if is_message:
                processed_lines.append(line)
            elif line.strip() and not re.match(skip_pattern, line, re.IGNORECASE):
                # Add non-empty lines that might be continuation of messages
                processed_lines.append(line)

        # Return content if it has any conversation
        if has_valid_content and has_conversation and len(processed_lines) >= 3:
            result = '\n'.join(processed_lines)
            print(f"DEBUG: Processed chat content: {len(result)} chars, {len(processed_lines)} lines")
            return result
        
        print(f"DEBUG: Chat rejected: valid_content={has_valid_content}, conversation={has_conversation}, lines={len(processed_lines)}")
        return ''

def cleanup_session_state():
    """Clean up old session data"""
    max_age = 3600  # 1 hour
    now = time.time()
    # Note: This function needs to be adapted for Flask session management
    pass

class RateLimiter:
    def __init__(self, calls_per_minute=60):
        self.calls_per_minute = calls_per_minute
        self.calls = []
    
    def wait_if_needed(self):
        now = time.time()
        self.calls = [t for t in self.calls if now - t < 60]
        if len(self.calls) >= self.calls_per_minute:
            time.sleep(60 - (now - self.calls[0]))
        self.calls.append(now)

def cleanup_temp_files():
    """Clean up temporary audio files"""
    temp_dir = tempfile.gettempdir()
    pattern = "qa_engine_*.wav"
    for f in glob.glob(os.path.join(temp_dir, pattern)):
        try:
            os.remove(f)
        except OSError:
            pass
