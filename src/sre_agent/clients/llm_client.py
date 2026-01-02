"""LLM Client for vLLM backend."""

import logging
import time
from typing import Optional

from openai import OpenAI

from ..config import LLMConfig

logger = logging.getLogger("sre_agent.llm")


class LLMClient:
    """
    Simple LLM client wrapping OpenAI client for local vLLM server.
    
    Uses OpenAI-compatible API to communicate with vLLM.
    """

    def __init__(self, config: LLMConfig):
        """
        Initialize LLM client.
        
        Args:
            config: LLM configuration with endpoint and model settings.
        """
        self.config = config
        self.client = OpenAI(
            base_url=config.base_url,
            api_key="not-needed",  # vLLM doesn't require API key
        )
        self.model = config.model
        self.temperature = config.temperature
        self.max_tokens = config.max_tokens

    def inference(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Run inference with system and user prompts.
        
        Args:
            system_prompt: System message for the LLM.
            user_prompt: User query/prompt.
            temperature: Override default temperature.
            max_tokens: Override default max tokens.
            
        Returns:
            LLM response text.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return self._chat_completion(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def chat(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Run chat completion with message history.
        
        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Override default temperature.
            max_tokens: Override default max tokens.
            
        Returns:
            LLM response text.
        """
        return self._chat_completion(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _chat_completion(
        self,
        messages: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Internal method to run chat completion.
        
        Args:
            messages: List of message dicts.
            temperature: Temperature setting.
            max_tokens: Max tokens setting.
            
        Returns:
            LLM response text.
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        logger.debug(f"LLM request: {len(messages)} messages, temp={temp}, max_tokens={tokens}")

        try:
            # Build request parameters
            request_params = {
                "model": self.model,
                "messages": messages,
            }
            
            # Reasoning models (like o1, gpt-oss) have different requirements
            if getattr(self.config, 'is_reasoning_model', False):
                # Reasoning models:
                # - Don't support temperature (or must be 1)
                # - Use max_completion_tokens instead of max_tokens
                # - May support reasoning_effort
                request_params["max_completion_tokens"] = tokens
                
                # Add reasoning_effort if supported
                reasoning_effort = getattr(self.config, 'reasoning_effort', 'medium')
                if reasoning_effort:
                    request_params["reasoning_effort"] = reasoning_effort
                    
                logger.debug(f"Using reasoning model params: max_completion_tokens={tokens}, reasoning_effort={reasoning_effort}")
            else:
                # Standard models use temperature and max_tokens
                request_params["temperature"] = temp
                request_params["max_tokens"] = tokens
            
            # Add extra parameters from config if present
            if hasattr(self.config, 'extra_params') and self.config.extra_params:
                request_params.update(self.config.extra_params)
            
            # Retry logic for reasoning models that may have intermittent errors
            max_retries = 3 if getattr(self.config, 'is_reasoning_model', False) else 1
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    response = self.client.chat.completions.create(**request_params)
                    result = response.choices[0].message.content
                    logger.debug(f"LLM response: {result[:200]}...")
                    return result
                except Exception as e:
                    last_error = e
                    error_msg = str(e)
                    # Retry on known intermittent reasoning model errors
                    if "Expected 2 output messages" in error_msg and attempt < max_retries - 1:
                        logger.warning(f"Reasoning model error (attempt {attempt + 1}/{max_retries}): {error_msg}")
                        time.sleep(1)
                        continue
                    # Don't retry other errors
                    raise
            
            # Should not reach here, but just in case
            raise last_error

        except Exception as e:
            logger.error(f"LLM inference failed: {e}")
            raise
