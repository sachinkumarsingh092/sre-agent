"""Conversation memory management with token tracking and summarization."""

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..clients import LLMClient

logger = logging.getLogger("sre_agent.memory")


@dataclass
class ConversationMemory:
    """
    Memory management for agent conversations.
    
    Tracks message history and estimated token count.
    Automatically summarizes old messages when approaching context limits.
    """
    
    messages: list[dict] = field(default_factory=list)
    max_messages: int = 20
    max_tokens: int = 6000
    summary: Optional[str] = None
    
    def estimated_tokens(self) -> int:
        """
        Estimate token count from message content.
        
        Uses rough approximation of ~4 characters per token.
        This is conservative for English text and errs on the side of
        triggering summarization earlier rather than hitting context limits.
        """
        total_chars = sum(len(m.get("content", "")) for m in self.messages)
        if self.summary:
            total_chars += len(self.summary)
        return total_chars // 4
    
    def should_summarize(self) -> bool:
        """Check if conversation has grown too large and needs summarization."""
        return (
            self.estimated_tokens() > self.max_tokens 
            or len(self.messages) > self.max_messages
        )
    
    def add(self, message: dict) -> None:
        """Add a message to the conversation history."""
        self.messages.append(message)
    
    def get_messages_for_llm(self) -> list[dict]:
        """
        Return messages formatted for LLM consumption.
        
        If a summary exists from previous context compression,
        prepends it as a system message so the LLM has historical context.
        """
        if self.summary:
            summary_message = {
                "role": "system",
                "content": f"Previous context summary:\n{self.summary}"
            }
            return [summary_message] + self.messages
        return self.messages
    
    def summarize_old_messages(self, llm: "LLMClient") -> None:
        """
        Summarize old messages to compress context.
        
        Keeps the most recent 10 messages and summarizes older ones.
        The summary is prepended to future LLM calls via get_messages_for_llm().
        
        Args:
            llm: LLM client for generating summaries.
        """
        if len(self.messages) <= 10:
            logger.debug("Not enough messages to summarize")
            return
        
        # Split: keep recent 10, summarize older ones
        old_messages = self.messages[:-10]
        self.messages = self.messages[-10:]
        
        logger.info(
            f"Summarizing {len(old_messages)} old messages, keeping {len(self.messages)} recent"
        )
        
        # Format old messages for summarization (truncate each to avoid huge prompts)
        history_lines = []
        for m in old_messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")[:500]
            if len(m.get("content", "")) > 500:
                content += "..."
            history_lines.append(f"[{role}]: {content}")
        
        history = "\n\n".join(history_lines)
        
        summary_prompt = f"""Summarize the key findings from this conversation history.
Focus on:
- What was discovered about the system state
- What commands were executed and their results
- Any error messages or issues identified
- Progress made toward diagnosis/mitigation

Provide a concise 2-3 sentence summary:

{history}"""
        
        try:
            new_summary = llm.inference(
                system_prompt="You are a summarizer. Extract key diagnostic findings and actions taken. Be concise.",
                user_prompt=summary_prompt,
                max_tokens=200
            )
            
            # Merge with existing summary if present
            if self.summary:
                self.summary = f"{self.summary}\n\n{new_summary}"
            else:
                self.summary = new_summary
            
            logger.info(f"Generated summary: {new_summary[:100]}...")
            
        except Exception as e:
            logger.warning(f"Failed to generate summary: {e}")
            # Continue without summary rather than failing
    
    def clear(self) -> None:
        """Clear all messages and summary."""
        self.messages = []
        self.summary = None
    
    def __len__(self) -> int:
        """Return number of messages in history."""
        return len(self.messages)
