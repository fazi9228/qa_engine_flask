import re
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Tuple, Optional ,Any
import uuid
import io

class ChatAnonymizer:
    """
    Anonymize sensitive information in chat transcripts using Python regex patterns
    Uses the same proven chat extraction logic as the batch analysis system
    """
    
    def __init__(self):
        # Counter for consistent replacement within same chat
        self.replacement_counters = {
            'phone': 0,
            'email': 0,
            'otp': 0,
            'dob': 0,
            'id_number': 0,
            'bank_account': 0,
            'credit_card': 0,
            'wallet': 0,
            'transaction_id': 0,
            'reference_number': 0
        }
        
        # Store original->anonymized mappings for consistency
        self.anonymization_map = {}
        
        # Patterns for different types of sensitive information
        self.patterns = self._initialize_patterns()
    
    def _initialize_patterns(self):
        """
        Initialize regex patterns for different types of sensitive information.
        UPDATED: Patterns now ignore numbers preceded by an ID prefix like 'MS-'.
    
        """
        return {
            # Phone numbers - Various international formats
            'phone': [
                r'\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b',
                # MODIFIED: Added a negative lookbehind to ignore numbers with a clear ID prefix
                r'\b(?<![A-Z]{2}-)(?:\+?[1-9][0-9]{0,3}[-.\s]?)?[0-9]{7,15}\b',
            ],
            
            # Email addresses
            'email': [
                r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            ],
            
            # OTP codes - 4-8 digit numbers
            'otp': [
                r'\b(?:OTP|otp|code|Code|verification|Verification)[\s:]*([0-9]{4,8})\b',
                r'\b([0-9]{6})\b(?=.*(?:OTP|otp|code|verification))',
            ],
            
            # Date of Birth - Various formats
            'dob': [
                r'\b([0-3]?[0-9])[-/.]([0-1]?[0-9])[-/.]([12][0-9]{3})\b',
                r'\b([12][0-9]{3})[-/.]([0-1]?[0-9])[-/.]([0-3]?[0-9])\b',
            ],
            
            # National ID / Passport
            'id_number': [
                r'\b[A-Z]{1,2}[0-9]{6,9}\b',
                # MODIFIED: Added a negative lookbehind to ignore numbers with a clear ID prefix
                r'\b(?<![A-Z]{2}-)(?<!Chat[\s_#])(?<!Case[\s_#])[0-9]{9,12}\b',
                r'\b[A-Z][0-9]{8}\b',
            ],
            
            # Bank account numbers
            'bank_account': [
                # MODIFIED: Added a negative lookbehind to ignore numbers with a clear ID prefix
                r'\b(?<![A-Z]{2}-)(?<!Chat[\s_#])(?<!ID[\s:])(?<!#)[0-9]{8,20}\b',
                r'\b[A-Z]{2}[0-9]{2}[A-Z0-9]{4}[0-9]{7}([A-Z0-9]?){0,16}\b',
            ],
            
            # Credit card numbers
            'credit_card': [
                r'\b4[0-9]{12}(?:[0-9]{3})?\b',
                r'\b5[1-5][0-9]{14}\b',
                r'\b3[47][0-9]{13}\b',
                r'\b[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}[-\s]?[0-9]{4}\b',
            ],
            
            # Wallet addresses and Transaction IDs
            'wallet': [
                r'\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b',
                r'\b0x[a-fA-F0-9]{40}\b',
                r'\bT[A-Za-z0-9]{33}\b',
            ],
            'transaction_id': [
                r'\b[a-fA-F0-9]{64}\b',
                r'\b0x[a-fA-F0-9]{64}\b',
            ],
        }
    
    def _is_system_identifier(self, text, match_position, original_value):
        """
        Check if a matched number is a system identifier that should NOT be anonymized.
        UPDATED: Now recognizes if a number is part of a [PREFIX]-[NUMBER] header.
    
        """
        # Get the full line where the matched number was found
        line_start = text.rfind('\n', 0, match_position) + 1
        line_end = text.find('\n', match_position)
        if line_end == -1:
            line_end = len(text)
        context_line = text[line_start:line_end].strip()

        # NEW: Check if the entire line matches the [PREFIX]-[NUMBER] format
        if re.fullmatch(r'[A-Z]{2,}-\d+', context_line, re.IGNORECASE):
            return True

        # PRIORITY 1: Check for chat or case numbers specifically
        id_patterns = [
            rf'\b(Chat|Case)[\s_#]*{re.escape(original_value)}(?!\d)',
            rf'\b(Chat|Case)[\s_#]+ID[\s:]*{re.escape(original_value)}(?!\d)',
            rf'^[A-Z]{2,}[\s:-]*(Chat|Case)[\s_#]*{re.escape(original_value)}(?!\d)',
            rf'\b(chat|case)\b.*?[A-Z]{2,}-\s*{re.escape(original_value)}(?!\d)'
        ]
        for pattern in id_patterns:
            if re.search(pattern, text[max(0, match_position-100):match_position+100], re.IGNORECASE):
                return True

        # PRIORITY 2: Check for other system identifiers
        preserve_patterns = [
            r'\b(?:session|ticket|order|conversation|transcript)[\s_#:]*' + re.escape(original_value) + r'(?!\d)',
            r'#[\s]*' + re.escape(original_value) + r'(?!\d)',
        ]
        for pattern in preserve_patterns:
            if re.search(pattern, text[max(0, match_position-100):match_position+100], re.IGNORECASE):
                return True

        # PRIORITY 3: Check for keywords on the same line
        if re.match(r'^(?:Chat|Case|Session|Ticket|Order|ID|Reference|Transaction)[\s_#:]*' + re.escape(original_value), context_line, re.IGNORECASE):
            return True
                
        return False

    def _generate_replacement(self, data_type: str, original_value: str) -> str:
        """Generate consistent replacement for sensitive data"""
        # Create a hash-based replacement for consistency
        hash_input = f"{data_type}_{original_value}".encode()
        hash_value = hashlib.md5(hash_input).hexdigest()[:8].upper()
        
        self.replacement_counters[data_type] += 1
        counter = self.replacement_counters[data_type]
        
        # Generate appropriate replacement based on data type
        replacements = {
            'phone': f"+XX-XXX-XXX-{counter:04d}",
            'email': f"user{counter}@anonymized.com",
            'otp': f"XX{counter:04d}",
            'dob': f"XX/XX/{1900 + (counter % 50)}",  # Keep it realistic
            'id_number': f"ID{hash_value}",
            'bank_account': f"ACCT{counter:012d}",
            'credit_card': f"XXXX-XXXX-XXXX-{counter:04d}",
            'wallet': f"WALLET{hash_value}",
            'transaction_id': f"TX{hash_value}",
            'reference_number': f"REF{hash_value}"
        }
        
        return replacements.get(data_type, f"ANON_{data_type.upper()}_{counter}")
    
    def anonymize_text(self, text: str) -> Tuple[str, Dict]:
        """
        Anonymize sensitive information in text
        """
        anonymized_text = text
        anonymization_report = {
            'total_replacements': 0,
            'replacements_by_type': {},
            'patterns_found': []
        }
        
        # Process each type of sensitive information
        for data_type, patterns in self.patterns.items():
            type_replacements = 0
            
            for pattern in patterns:
                matches = list(re.finditer(pattern, anonymized_text, re.IGNORECASE))
                
                for match in reversed(matches):  # Reverse to maintain string positions
                    original_value = match.group(0)
                    match_position = match.start()
                    
                    # Skip if already anonymized
                    if original_value.startswith(('XX', 'ANON_', 'user', 'ACCT', 'WALLET', 'TX', 'REF', 'ID')):
                        continue
                    
                    # FIXED: Pass original_value to the system identifier check
                    if self._is_system_identifier(text, match_position, original_value):
                        print(f"Preserving system identifier: '{original_value}'")
                        continue
                    
                    # Check if we've already anonymized this value
                    if original_value in self.anonymization_map:
                        replacement = self.anonymization_map[original_value]
                    else:
                        replacement = self._generate_replacement(data_type, original_value)
                        self.anonymization_map[original_value] = replacement
                    
                    # Replace in text
                    start, end = match.span()
                    anonymized_text = anonymized_text[:start] + replacement + anonymized_text[end:]
                    
                    type_replacements += 1
                    anonymization_report['patterns_found'].append({
                        'type': data_type,
                        'original': original_value,
                        'replacement': replacement,
                        'position': start
                    })
            
            if type_replacements > 0:
                anonymization_report['replacements_by_type'][data_type] = type_replacements
                anonymization_report['total_replacements'] += type_replacements
        
        return anonymized_text, anonymization_report
    
    def _split_text_into_chats(self, text: str) -> List[Dict[str, Any]]:
        """
        Use the EXACT same logic as EnhancedChatProcessor for splitting chats
        This ensures compatibility with the QA analysis system
        """
        chats = []
        
        # Use the same minimum requirements as batch analysis
        MIN_LINES = 3
        MIN_CHARS = 50
        
        # Use the EXACT same patterns as EnhancedChatProcessor
        chat_start_patterns = [
            r"(?:^|\s)Chat\s+(?:ID\s*:?\s*)?(\d+)(?!\d)",  # Match "Chat 01271153"
            r"(?:^|\s)Chat\s*#\s*(\d+)(?!\d)",             # Match "Chat #01271153"
            r"^[A-Z]{2,}\s*[:-]?\s*Chat\s+(\d+)(?!\d)",    # Match "TH: Chat 01271153"
            r"^[A-Z]{2,}\s*[:-]?\s*Chat\s*#\s*(\d+)(?!\d)" # Match "TH: Chat #01271153"
        ]
        
        # Create combined pattern
        combined_pattern = '|'.join(f"(?:{pattern})" for pattern in chat_start_patterns)
        
        # Split by chat number patterns
        segments = re.split(f"({combined_pattern})", text, flags=re.IGNORECASE | re.MULTILINE)
        
        # Filter out empty segments
        segments = [segment for segment in segments if segment and not segment.isspace()]
        
        # Process segments using the same logic as batch analysis
        current_chat = ""
        chat_counter = 0
        is_header = False
        
        for i, segment in enumerate(segments):
            # Check if segment is a chat boundary
            if re.match(combined_pattern, segment, re.IGNORECASE):
                # Process previous chat if it exists and meets minimum requirements
                if current_chat.strip():
                    lines = [line for line in current_chat.split('\n') if line.strip()]
                    if len(lines) >= MIN_LINES and len(current_chat.strip()) >= MIN_CHARS:
                        chat_id = self._extract_chat_id(current_chat) or f"Chat_{chat_counter}"
                        timestamp = self._extract_timestamp(current_chat)
                        processed_content = self._clean_and_process_chat(current_chat)
                        
                        if processed_content:
                            chats.append({
                                'id': chat_id,
                                'content': current_chat,
                                'timestamp': timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                                'processed_content': processed_content
                            })
                            chat_counter += 1
                
                current_chat = segment
                is_header = True
            else:
                if is_header or not current_chat:
                    current_chat += segment
                    is_header = False
                else:
                    current_chat += segment
        
        # Process final chat
        if current_chat.strip():
            lines = [line for line in current_chat.split('\n') if line.strip()]
            if len(lines) >= MIN_LINES and len(current_chat.strip()) >= MIN_CHARS:
                chat_id = self._extract_chat_id(current_chat) or f"Chat_{chat_counter}"
                timestamp = self._extract_timestamp(current_chat)
                processed_content = self._clean_and_process_chat(current_chat)
                
                if processed_content:
                    chats.append({
                        'id': chat_id,
                        'content': current_chat,
                        'timestamp': timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'processed_content': processed_content
                    })
        
        return chats
    
    def _extract_chat_id(self, chat_text: str) -> Optional[str]:
        """Extract chat ID using the same logic as EnhancedChatProcessor"""
        patterns = [
            r"(?:^|\s)Chat\s+(?:ID\s*:?\s*)?(\d+)(?!\d)",  # Match "Chat 01271153"
            r"(?:^|\s)Chat\s*#\s*(\d+)(?!\d)",             # Match "Chat #01271153"
            r"^[A-Z]{2,}\s*[:-]?\s*Chat\s+(\d+)(?!\d)",    # Match "TH: Chat 01271153"
            r"^[A-Z]{2,}\s*[:-]?\s*Chat\s*#\s*(\d+)(?!\d)" # Match "TH: Chat #01271153"
        ]
        
        for pattern in patterns:
            match = re.search(pattern, chat_text, re.IGNORECASE)
            if match:
                chat_id = match.group(1)
                
                # Check for duplicated numbers (same logic as batch analysis)
                if len(chat_id) >= 16:
                    half_len = len(chat_id) // 2
                    if chat_id[:half_len] == chat_id[half_len:2*half_len]:
                        chat_id = chat_id[:half_len]
                    elif chat_id[:6] == chat_id[half_len:half_len+6]:
                        chat_id = chat_id[:half_len]
                
                return f"Chat_{chat_id}"
        
        # If no valid chat ID found, generate a hash from the content
        content_sample = chat_text[:100].strip()
        if content_sample:
            hash_obj = hashlib.md5(content_sample.encode())
            return f"Chat_{hash_obj.hexdigest()[:8]}"
        
        return None
    
    def _extract_timestamp(self, chat_text: str) -> Optional[str]:
        """Extract timestamp using the same logic as EnhancedChatProcessor"""
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
                    for fmt in [
                        "%A, %B %d, %Y, %H:%M:%S",
                        "%A, %B %d, %Y %H:%M:%S",
                        "%Y-%m-%d %H:%M:%S"
                    ]:
                        try:
                            parsed_time = datetime.strptime(timestamp_str, fmt)
                            return parsed_time.strftime("%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            continue
                except Exception:
                    pass
        return None
    
    def _clean_and_process_chat(self, chat_text: str) -> str:
        """Clean and format chat content using the same logic as EnhancedChatProcessor"""
        lines = chat_text.split('\n')
        processed_lines = []
        has_valid_content = False
        speaker_patterns = {
            'customer': [
                r'^(?:Customer|Client|Visitor|User|Guest)',
                r'^\(\d+[ms]\)\s*(?:Customer|Client|Visitor|User|Guest)',
                r'^.*?(?:Customer|Client|Visitor|User|Guest)\s*:'
            ],
            'agent': [
                r'^(?:Agent|Support|Assistant|Representative|Bot|Chatbot|Pepper)',
                r'^\(\d+[ms]\)\s*(?:Agent|Support|Assistant|Representative|Bot|Chatbot|Pepper)',
                r'^.*?(?:Agent|Support|Assistant|Representative|Bot|Chatbot|Pepper)\s*:'
            ]
        }

        skip_patterns = [
            r'^\s*\{ChatWindowButton:',
            r'^\s*Page \d+ of \d+',
            r'^\s*Report generated',
            r'^\s*[-=*_]{3,}\s*$'
        ]

        skip_pattern = '|'.join(skip_patterns)
        has_conversation = False

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if re.match(skip_pattern, line, re.IGNORECASE):
                continue

            is_message = False
            # Check for customer messages
            for pattern in speaker_patterns['customer']:
                if re.match(pattern, line, re.IGNORECASE):
                    is_message = True
                    has_valid_content = True
                    has_conversation = True
                    line = re.sub(r'^\(\d+[ms]\)\s*', '', line)
                    line = re.sub(r'^.*?(?:Customer|Client|Visitor|User|Guest)\s*:', 'Customer:', line, flags=re.IGNORECASE)
                    break

            if not is_message:
                for pattern in speaker_patterns['agent']:
                    if re.match(pattern, line, re.IGNORECASE):
                        is_message = True
                        has_valid_content = True
                        has_conversation = True
                        line = re.sub(r'^\(\d+[ms]\)\s*', '', line)
                        if re.match(r'^.*?(Bot|Chatbot|Pepper)\s*:', line, re.IGNORECASE):
                            line = re.sub(r'^.*?(Bot|Chatbot|Pepper)\s*:', r'\1:', line, flags=re.IGNORECASE)
                        else:
                            line = re.sub(r'^.*?(?:Agent|Support|Assistant|Representative)\s*:', 'Agent:', line, flags=re.IGNORECASE)
                        break

            if is_message:
                processed_lines.append(line)
            elif line.strip():
                processed_lines.append(line)

        if has_valid_content and has_conversation:
            return '\n'.join(processed_lines)
        return ''
    
    def anonymize_multiple_chats(self, file_content: str) -> Dict:
        """
        Anonymize multiple chats from a file using the proven batch analysis logic
        """
        # Reset counters for new file
        self.replacement_counters = {key: 0 for key in self.replacement_counters}
        self.anonymization_map = {}
        
        # Use the same chat splitting logic as batch analysis
        individual_chats = self._split_text_into_chats(file_content)
        
        if not individual_chats:
            return {
                'error': 'No chats found in the uploaded file',
                'timestamp': datetime.now().isoformat(),
                'file_stats': {
                    'original_length': len(file_content),
                    'line_count': len(file_content.split('\n'))
                }
            }
        
        # Anonymize each chat
        anonymized_chats = []
        total_replacements = 0
        combined_report = {
            'total_replacements': 0,
            'replacements_by_type': {},
            'patterns_found': []
        }
        
        for chat in individual_chats:
            print(f"Anonymizing chat: {chat['id']}")
            
            # Anonymize this chat
            anonymized_text, report = self.anonymize_text(chat['content'])
            
            anonymized_chats.append({
                'original_id': chat['id'],
                'original_content': chat['content'],
                'anonymized_content': anonymized_text,
                'stats': {
                    'original_length': len(chat['content']),
                    'anonymized_length': len(anonymized_text),
                    'line_count': len(chat['content'].split('\n'))
                },
                'anonymization_report': report
            })
            
            # Combine reports
            total_replacements += report['total_replacements']
            combined_report['patterns_found'].extend(report['patterns_found'])
            
            for data_type, count in report['replacements_by_type'].items():
                combined_report['replacements_by_type'][data_type] = \
                    combined_report['replacements_by_type'].get(data_type, 0) + count
        
        combined_report['total_replacements'] = total_replacements
        
        # Create combined anonymized content preserving original chat structure
        combined_anonymized = '\n\n'.join([
            chat['anonymized_content']
            for chat in anonymized_chats
        ])
        
        result = {
            'original_length': len(file_content),
            'anonymized_length': len(combined_anonymized),
            'anonymized_transcript': combined_anonymized,
            'individual_chats': anonymized_chats,
            'chat_count': len(individual_chats),
            'anonymization_report': combined_report,
            'timestamp': datetime.now().isoformat(),
            'anonymization_id': str(uuid.uuid4())[:8]
        }
        
        return result
    
    def anonymize_chat_transcript(self, transcript: str) -> Dict:
        """
        Anonymize a complete chat transcript (single chat)
        """
        # Reset counters for new transcript
        self.replacement_counters = {key: 0 for key in self.replacement_counters}
        self.anonymization_map = {}
        
        anonymized_text, report = self.anonymize_text(transcript)
        
        result = {
            'original_length': len(transcript),
            'anonymized_length': len(anonymized_text),
            'anonymized_transcript': anonymized_text,
            'anonymization_report': report,
            'timestamp': datetime.now().isoformat(),
            'anonymization_id': str(uuid.uuid4())[:8]
        }
        
        return result
    
    def get_anonymization_summary(self, report: Dict) -> str:
        """Generate human-readable summary of anonymization"""
        # Handle both single chat and multiple chat reports
        if 'chat_count' in report:
            # Multiple chats
            if report['anonymization_report']['total_replacements'] == 0:
                return f"Processed {report['chat_count']} chats. No sensitive information detected."
            
            summary_lines = [
                f"🔒 Processed {report['chat_count']} chats",
                f"🔒 Anonymized {report['anonymization_report']['total_replacements']} sensitive items total:",
                ""
            ]
        else:
            # Single chat
            if report['anonymization_report']['total_replacements'] == 0:
                return "No sensitive information detected."
            
            summary_lines = [
                f"🔒 Anonymized {report['anonymization_report']['total_replacements']} sensitive items:",
                ""
            ]
        
        type_names = {
            'phone': '📞 Phone numbers',
            'email': '📧 Email addresses', 
            'otp': '🔢 OTP codes',
            'dob': '📅 Dates of birth',
            'id_number': '🆔 ID/Passport numbers',
            'bank_account': '🏦 Bank account numbers',
            'credit_card': '💳 Credit card numbers',
            'wallet': '💰 Wallet addresses',
            'transaction_id': '🔗 Transaction IDs',
            'reference_number': '📋 Reference numbers'
        }
        
        # Get the report data
        replacements_by_type = report.get('anonymization_report', {}).get('replacements_by_type', {})
        
        for data_type, count in replacements_by_type.items():
            type_name = type_names.get(data_type, data_type.title())
            summary_lines.append(f"  {type_name}: {count}")
        
        return "\n".join(summary_lines)

# Test function to verify it works with your chat format
def test_anonymizer():
    """Test with Vietnamese chat format"""
    anonymizer = ChatAnonymizer()
    
    sample_text = """Chat 01267967
Chat Started: Wednesday, February 26, 2025, 10:27:21 (+0800)
( 2s ) Pepper Chatbot: Hi, I'm Pepperstone's chatbot, but you can call me Pepper 😃
( 12s ) Visitor: Tiếng Việt

Agent Chatbot successfully transferred the chat to skill
Chat Started: Wednesday, February 26, 2025, 10:27:35 (+0800)
Chat Origin: Chat EN
Chat Transferred From Pepper Chatbot To Support
( 1m 32s ) Visitor: cho tôi hỏi tại sao tôi ko thể sử dụng thẻ tín dụng +1-555-123-4567 để nạp tiền vào tài khoản?
( 2m 57s ) Support: Dạ em hiểu là Anh/Chị đang cần giải đáp thông tin về phương thức nạp tiền tại Pepperstone ạ.

*************
Chat 01273017

Chat Started: Wednesday, March 05, 2025, 16:07:05 (+0800)
( 19s ) Visitor: Cần thay đổi số điện thoại john@test.com
( 3m 38s ) Support: Cám ơn quý khách đã liên hệ với đội ngũ hỗ trợ Pepperstone VN.
"""
    
    result = anonymizer.anonymize_multiple_chats(sample_text)
    
    print("=== ANONYMIZATION TEST ===")
    print(f"Found {result['chat_count']} chats")
    print(f"Total replacements: {result['anonymization_report']['total_replacements']}")
    print("\nAnonymized content:")
    print(result['anonymized_transcript'])
    
    return result

if __name__ == "__main__":
    test_anonymizer()
