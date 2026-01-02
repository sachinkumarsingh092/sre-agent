"""Action stack for tracking and rolling back operations."""

import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Any

logger = logging.getLogger("sre_agent.action_stack")


@dataclass
class RollbackInfo:
    """Information needed to rollback an action."""
    
    rollback_type: str  # "command" or "state"
    content: str  # kubectl command or YAML state
    
    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ActionRecord:
    """Record of an action that can be rolled back."""
    
    action: str  # The action/command that was executed
    action_type: str  # Type of action (delete, scale, patch, etc.)
    rollback_info: Optional[RollbackInfo]  # How to rollback
    original_state: Optional[dict]  # State before action (for reference)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    success: bool = True
    
    def to_dict(self) -> dict:
        d = asdict(self)
        if self.rollback_info:
            d["rollback_info"] = self.rollback_info.to_dict()
        return d


class ActionStack:
    """
    Thread-safe stack for tracking actions that can be rolled back.
    
    Each action pushed to the stack includes:
    - The action/command that was executed
    - Information on how to rollback the action
    - Original state before the action
    """
    
    def __init__(self):
        self._stack: list[ActionRecord] = []
        self._lock = threading.Lock()
    
    def push(self, record: ActionRecord) -> None:
        """
        Push an action record to the stack.
        
        Args:
            record: The action record to push.
        """
        with self._lock:
            self._stack.append(record)
            logger.info(f"Pushed action to stack: {record.action}")
    
    def pop(self) -> Optional[ActionRecord]:
        """
        Pop the most recent action from the stack.
        
        Returns:
            The most recent ActionRecord, or None if stack is empty.
        """
        with self._lock:
            if not self._stack:
                return None
            record = self._stack.pop()
            logger.info(f"Popped action from stack: {record.action}")
            return record
    
    def peek(self) -> Optional[ActionRecord]:
        """
        Look at the most recent action without removing it.
        
        Returns:
            The most recent ActionRecord, or None if stack is empty.
        """
        with self._lock:
            if not self._stack:
                return None
            return self._stack[-1]
    
    def is_empty(self) -> bool:
        """Check if the stack is empty."""
        with self._lock:
            return len(self._stack) == 0
    
    def size(self) -> int:
        """Get the number of actions in the stack."""
        with self._lock:
            return len(self._stack)
    
    def clear(self) -> None:
        """Clear all actions from the stack."""
        with self._lock:
            self._stack.clear()
            logger.info("Cleared action stack")
    
    def get_all(self) -> list[ActionRecord]:
        """Get all actions in the stack (oldest to newest)."""
        with self._lock:
            return list(self._stack)
    
    def to_list(self) -> list[dict]:
        """Convert stack to list of dicts for serialization."""
        with self._lock:
            return [record.to_dict() for record in self._stack]
