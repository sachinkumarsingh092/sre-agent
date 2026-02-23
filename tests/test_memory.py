"""Tests for ConversationMemory."""

import pytest
from unittest.mock import MagicMock

from sre_agent.agent.memory import ConversationMemory


class TestConversationMemory:
    """Test cases for ConversationMemory."""

    def test_init_defaults(self):
        """Test default initialization."""
        memory = ConversationMemory()
        assert memory.messages == []
        assert memory.max_messages == 20
        assert memory.max_tokens == 6000
        assert memory.summary is None

    def test_add_message(self):
        """Test adding messages."""
        memory = ConversationMemory()
        memory.add({"role": "user", "content": "Hello"})
        assert len(memory) == 1
        assert memory.messages[0]["content"] == "Hello"

    def test_estimated_tokens(self):
        """Test token estimation."""
        memory = ConversationMemory()
        # 40 characters / 4 = 10 tokens
        memory.add({"role": "user", "content": "a" * 40})
        assert memory.estimated_tokens() == 10

    def test_estimated_tokens_includes_summary(self):
        """Test that token estimation includes summary."""
        memory = ConversationMemory()
        memory.add({"role": "user", "content": "a" * 40})  # 10 tokens
        memory.summary = "b" * 80  # 20 tokens
        assert memory.estimated_tokens() == 30

    def test_should_summarize_by_tokens(self):
        """Test summarization trigger by token count."""
        memory = ConversationMemory(max_tokens=100)
        # Add enough content to exceed 100 tokens (400+ chars)
        memory.add({"role": "user", "content": "x" * 500})
        assert memory.should_summarize() is True

    def test_should_summarize_by_message_count(self):
        """Test summarization trigger by message count."""
        memory = ConversationMemory(max_messages=5)
        for i in range(6):
            memory.add({"role": "user", "content": f"msg{i}"})
        assert memory.should_summarize() is True

    def test_should_not_summarize_under_limits(self):
        """Test no summarization when under limits."""
        memory = ConversationMemory(max_messages=20, max_tokens=6000)
        memory.add({"role": "user", "content": "Short message"})
        assert memory.should_summarize() is False

    def test_get_messages_without_summary(self):
        """Test getting messages when no summary exists."""
        memory = ConversationMemory()
        memory.add({"role": "user", "content": "test"})
        messages = memory.get_messages_for_llm()
        assert len(messages) == 1
        assert messages[0]["content"] == "test"

    def test_get_messages_with_summary(self):
        """Test getting messages with summary prepended."""
        memory = ConversationMemory()
        memory.add({"role": "user", "content": "test"})
        memory.summary = "Previous context: found issue X"
        messages = memory.get_messages_for_llm()
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "Previous context summary" in messages[0]["content"]
        assert messages[1]["content"] == "test"

    def test_summarize_keeps_recent_messages(self):
        """Test that summarization keeps the last 10 messages."""
        memory = ConversationMemory()
        mock_llm = MagicMock()
        mock_llm.inference.return_value = "Summary of old messages"

        # Add 15 messages
        for i in range(15):
            memory.add({"role": "user", "content": f"Message {i}"})

        memory.summarize_old_messages(mock_llm)

        # Should keep last 10 messages
        assert len(memory) == 10
        # Last message should be "Message 14"
        assert memory.messages[-1]["content"] == "Message 14"
        # First message should be "Message 5"
        assert memory.messages[0]["content"] == "Message 5"

    def test_summarize_creates_summary(self):
        """Test that summarization creates a summary."""
        memory = ConversationMemory()
        mock_llm = MagicMock()
        mock_llm.inference.return_value = "Found pod crash in namespace default"

        for i in range(12):
            memory.add({"role": "user", "content": f"Message {i}"})

        memory.summarize_old_messages(mock_llm)

        assert memory.summary == "Found pod crash in namespace default"
        mock_llm.inference.assert_called_once()

    def test_summarize_chains_summaries(self):
        """Test that multiple summarizations chain together."""
        memory = ConversationMemory()
        mock_llm = MagicMock()

        # First summarization
        mock_llm.inference.return_value = "First summary"
        for i in range(12):
            memory.add({"role": "user", "content": f"Batch1 {i}"})
        memory.summarize_old_messages(mock_llm)
        
        # Second summarization
        mock_llm.inference.return_value = "Second summary"
        for i in range(12):
            memory.add({"role": "user", "content": f"Batch2 {i}"})
        memory.summarize_old_messages(mock_llm)

        assert "First summary" in memory.summary
        assert "Second summary" in memory.summary

    def test_summarize_skips_if_few_messages(self):
        """Test that summarization is skipped with <= 10 messages."""
        memory = ConversationMemory()
        mock_llm = MagicMock()

        for i in range(8):
            memory.add({"role": "user", "content": f"Message {i}"})

        memory.summarize_old_messages(mock_llm)

        # Should not call LLM
        mock_llm.inference.assert_not_called()
        # Should keep all messages
        assert len(memory) == 8

    def test_clear(self):
        """Test clearing memory."""
        memory = ConversationMemory()
        memory.add({"role": "user", "content": "test"})
        memory.summary = "old summary"
        memory.clear()
        assert len(memory) == 0
        assert memory.summary is None


class TestAgentContextIntegration:
    """Test AgentContext with ConversationMemory integration."""

    def test_agent_context_has_memory(self):
        """Test that AgentContext initializes with memory."""
        from sre_agent.agent import AgentContext
        ctx = AgentContext()
        assert isinstance(ctx.memory, ConversationMemory)
        assert len(ctx.memory) == 0

    def test_agent_context_memory_operations(self):
        """Test memory operations through AgentContext."""
        from sre_agent.agent import AgentContext
        ctx = AgentContext()
        ctx.memory.add({"role": "system", "content": "SRE prompt"})
        ctx.memory.add({"role": "user", "content": "Alert info"})
        assert len(ctx.memory) == 2
        assert ctx.memory.estimated_tokens() > 0
