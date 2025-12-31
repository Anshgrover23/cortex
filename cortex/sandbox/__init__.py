"""
Cortex Sandbox Module.

Provides isolated sandbox environments for testing packages
before promoting them to the main system.

Features:
- Firejail-based sandboxing for security isolation
- Environment lifecycle management (create, destroy, list)
- Package installation in sandboxes
- Automated testing framework
- Safe promotion to main system
"""

from cortex.sandbox.sandbox_executor import CommandBlocked, ExecutionResult, SandboxExecutor
from cortex.sandbox.sandbox_manager import (
    PromotionResult,
    SandboxEnvironment,
    SandboxManager,
    SandboxStatus,
)
from cortex.sandbox.sandbox_tester import SandboxTester, TestResult, TestSuiteResult

__all__ = [
    # Executor
    "SandboxExecutor",
    "ExecutionResult",
    "CommandBlocked",
    # Manager
    "SandboxManager",
    "SandboxEnvironment",
    "SandboxStatus",
    "PromotionResult",
    # Tester
    "SandboxTester",
    "TestResult",
    "TestSuiteResult",
]
