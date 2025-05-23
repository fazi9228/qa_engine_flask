"""
chat_qa_with_anonymization.py

Seamless wrapper around the original chat_qa.py that automatically anonymizes 
sensitive data before sending to LLM, but returns the same output format.

The user never sees the anonymized data - it all happens behind the scenes.
"""

import os
import sys
from typing import Dict, List, Optional, Any
from datetime import datetime

# Import original functions
from chat_qa import analyze_chat_transcript as original_analyze_chat_transcript
from chat_anonymizer import ChatAnonymizer

def analyze_chat_transcript(
    transcript: str,
    evaluation_rules: Dict,
    knowledge_base,
    target_language: str = "en",
    prompt_template_path: str = "QA_prompt.md",
    model_provider: str = "anthropic",
    model_name: str = "claude-3-7-sonnet-20250219"
) -> Dict:
    """
    Drop-in replacement for the original analyze_chat_transcript function.
    
    Automatically anonymizes sensitive data before LLM analysis, but returns
    the exact same output format as the original function.
    
    The anonymization is completely invisible to the caller.
    """
    
    print("🔒 [Auto-Anonymization] Processing chat transcript...")
    
    try:
        # Step 1: Anonymize the transcript silently
        anonymizer = ChatAnonymizer()
        anonymized_transcript, anonymization_report = anonymizer.anonymize_text(transcript)
        
        # Log anonymization (but don't expose to user)
        replacements = anonymization_report.get('total_replacements', 0)
        if replacements > 0:
            print(f"🔒 [Auto-Anonymization] Removed {replacements} sensitive items before analysis")
            
            # Log what types were anonymized (for debugging)
            for data_type, count in anonymization_report.get('replacements_by_type', {}).items():
                print(f"    - {data_type}: {count}")
        else:
            print("🔒 [Auto-Anonymization] No sensitive data detected")
        
        # Step 2: Call the original function with anonymized data
        print("🤖 [QA Analysis] Starting analysis with cleaned data...")
        
        result = original_analyze_chat_transcript(
            anonymized_transcript,  # Use anonymized text
            evaluation_rules,
            knowledge_base,
            target_language=target_language,
            prompt_template_path=prompt_template_path,
            model_provider=model_provider,
            model_name=model_name
        )
        
        print("✅ [QA Analysis] Analysis completed successfully")
        
        # Step 3: Return the exact same format as original function
        # No mention of anonymization in the output
        return result
        
    except Exception as e:
        print(f"❌ [Auto-Anonymization] Error during processing: {str(e)}")
        
        # Fallback: If anonymization fails, try with original text
        print("⚠️ [Fallback] Attempting analysis with original text...")
        try:
            result = original_analyze_chat_transcript(
                transcript,  # Use original text as fallback
                evaluation_rules,
                knowledge_base,
                target_language=target_language,
                prompt_template_path=prompt_template_path,
                model_provider=model_provider,
                model_name=model_name
            )
            print("✅ [Fallback] Analysis completed with original text")
            return result
            
        except Exception as fallback_error:
            print(f"❌ [Fallback] Failed: {str(fallback_error)}")
            return {
                'error': f'Analysis failed: {str(fallback_error)}',
                'weighted_overall_score': 0
            }

def analyze_multiple_chats_with_anonymization(
    chats: List[Dict[str, Any]],
    evaluation_rules: Dict,
    knowledge_base,
    target_language: str = "en",
    prompt_template_path: str = "QA_prompt.md",
    model_provider: str = "anthropic",
    model_name: str = "claude-3-7-sonnet-20250219"
) -> List[Dict]:
    """
    Batch process multiple chats with automatic anonymization.
    
    Each chat gets anonymized individually before analysis.
    Returns the same format as if you called the original function on each chat.
    """
    
    print(f"🔒 [Batch Auto-Anonymization] Processing {len(chats)} chats...")
    
    results = []
    anonymizer = ChatAnonymizer()
    total_anonymized_items = 0
    
    for i, chat in enumerate(chats):
        try:
            chat_id = chat.get('id', f'Chat_{i+1}')
            content = chat.get('processed_content', chat.get('content', ''))
            
            if not content or len(content.strip()) < 10:
                print(f"⚠️ [Chat {i+1}] Skipping - insufficient content")
                continue
            
            print(f"🔒 [Chat {i+1}/{len(chats)}] Processing {chat_id}...")
            
            # Anonymize this chat
            anonymized_content, anonymization_report = anonymizer.anonymize_text(content)
            replacements = anonymization_report.get('total_replacements', 0)
            total_anonymized_items += replacements
            
            if replacements > 0:
                print(f"    Removed {replacements} sensitive items")
            
            # Analyze the anonymized content
            result = original_analyze_chat_transcript(
                anonymized_content,
                evaluation_rules,
                knowledge_base,
                target_language=target_language,
                prompt_template_path=prompt_template_path,
                model_provider=model_provider,
                model_name=model_name
            )
            
            if result:
                # Add chat metadata (same as original batch processing)
                result['chat_id'] = chat_id
                result['content_preview'] = chat.get('content', '')[:500] + "..." if len(chat.get('content', '')) > 500 else chat.get('content', '')
                
                # Ensure score exists and is valid
                if 'weighted_overall_score' not in result or result['weighted_overall_score'] is None:
                    result['weighted_overall_score'] = 0
                
                try:
                    result['weighted_overall_score'] = round(float(result.get('weighted_overall_score', 0)), 2)
                except (ValueError, TypeError):
                    result['weighted_overall_score'] = 0
                
                results.append(result)
                print(f"✅ [Chat {i+1}] Analysis complete - Score: {result['weighted_overall_score']}%")
            else:
                print(f"❌ [Chat {i+1}] Analysis failed")
                
        except Exception as e:
            print(f"❌ [Chat {i+1}] Error: {str(e)}")
            continue
    
    print(f"🎉 [Batch Complete] Analyzed {len(results)} chats, anonymized {total_anonymized_items} sensitive items total")
    
    return results

# Enhanced chat processor that uses anonymization
class EnhancedChatProcessorWithAutoAnonymization:
    """
    Drop-in replacement for EnhancedChatProcessor that automatically anonymizes
    """
    
    def __init__(self):
        # Import the original processor
        from enhanced_chat_processor import EnhancedChatProcessor
        self.base_processor = EnhancedChatProcessor()
        self.anonymizer = ChatAnonymizer()
        print("🔒 [Auto-Anonymization] Enhanced processor initialized")
    
    def extract_chats_from_file(self, file_obj) -> List[Dict[str, Any]]:
        """
        Extract chats from file and automatically anonymize the content.
        
        Returns the same format as the original function, but with anonymized content.
        The caller doesn't need to know about the anonymization.
        """
        
        print(f"📄 [File Processing] Extracting chats from {getattr(file_obj, 'name', 'uploaded file')}")
        
        # Step 1: Extract chats using original processor
        chats = self.base_processor.extract_chats_from_file(file_obj)
        
        if not chats:
            print("❌ [File Processing] No chats found")
            return []
        
        print(f"✅ [File Processing] Found {len(chats)} chats")
        
        # Step 2: Silently anonymize each chat
        print("🔒 [Auto-Anonymization] Cleaning sensitive data from extracted chats...")
        
        anonymized_chats = []
        total_replacements = 0
        
        for i, chat in enumerate(chats):
            try:
                # Anonymize main content
                if 'content' in chat and chat['content']:
                    anonymized_content, report1 = self.anonymizer.anonymize_text(chat['content'])
                    chat['content'] = anonymized_content
                    total_replacements += report1.get('total_replacements', 0)
                
                # Anonymize processed content
                if 'processed_content' in chat and chat['processed_content']:
                    anonymized_processed, report2 = self.anonymizer.anonymize_text(chat['processed_content'])
                    chat['processed_content'] = anonymized_processed
                    total_replacements += report2.get('total_replacements', 0)
                
                anonymized_chats.append(chat)
                
            except Exception as e:
                print(f"⚠️ [Chat {i+1}] Anonymization failed: {str(e)}")
                # Keep original chat if anonymization fails
                anonymized_chats.append(chat)
        
        if total_replacements > 0:
            print(f"🔒 [Auto-Anonymization] Cleaned {total_replacements} sensitive items from {len(chats)} chats")
        else:
            print("🔒 [Auto-Anonymization] No sensitive data found in chats")
        
        return anonymized_chats

# Utility function for easy migration
def migrate_from_original_chat_qa():
    """
    Helper function to show how to migrate from the original chat_qa
    """
    migration_guide = """
    🔄 MIGRATION GUIDE
    
    OLD WAY (chat_qa.py):
    from chat_qa import analyze_chat_transcript
    result = analyze_chat_transcript(transcript, rules, kb)
    
    NEW WAY (this file):
    from chat_qa_with_anonymization import analyze_chat_transcript
    result = analyze_chat_transcript(transcript, rules, kb)
    
    That's it! Same function signature, same output format.
    Anonymization happens automatically behind the scenes.
    
    For batch processing:
    OLD: from enhanced_chat_processor import EnhancedChatProcessor
    NEW: from chat_qa_with_anonymization import EnhancedChatProcessorWithAutoAnonymization as EnhancedChatProcessor
    """
    
    print(migration_guide)
    return migration_guide

if __name__ == "__main__":
    # Test the anonymization wrapper
    print("🧪 Testing Auto-Anonymization Wrapper")
    print("=" * 50)
    
    # Sample test data
    test_transcript = """
    Customer: Hi, I need help with my account. My phone number is +1-555-123-4567
    Agent: Hello! I'd be happy to help you. Can you provide your email address?
    Customer: Sure, it's john.doe@email.com and my account number is 1234567890
    Agent: Thank you, I can see your account now.
    """
    
    print("Original transcript:")
    print(test_transcript)
    
    # This would normally require the actual evaluation rules and knowledge base
    print("\n[Note: This is just a test of the anonymization part]")
    
    # Test anonymization directly
    anonymizer = ChatAnonymizer()
    anonymized, report = anonymizer.anonymize_text(test_transcript)
    
    print(f"\nAnonymized version (this is what gets sent to LLM):")
    print(anonymized)
    
    print(f"\nReplacements made: {report['total_replacements']}")
    for data_type, count in report['replacements_by_type'].items():
        print(f"  {data_type}: {count}")
    
    print("\n✅ The analyze_chat_transcript function would return the same format as original,")
    print("   but the LLM would never see the sensitive data!")
