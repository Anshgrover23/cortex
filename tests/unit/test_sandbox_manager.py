#!/usr/bin/env python3
"""
Unit tests for SandboxManager and SandboxTester.

Tests cover:
- Environment lifecycle (create, destroy, list)
- Package operations (install, remove, list)
- Promotion to main system
- Automated testing framework
- Database operations
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from cortex.sandbox.sandbox_executor import ExecutionResult
from cortex.sandbox.sandbox_manager import (
    PromotionResult,
    SandboxEnvironment,
    SandboxManager,
    SandboxStatus,
)
from cortex.sandbox.sandbox_tester import SandboxTester, TestResult, TestSuiteResult


class TestSandboxEnvironment(unittest.TestCase):
    """Test SandboxEnvironment dataclass."""

    def test_create_environment(self):
        """Test creating a SandboxEnvironment."""
        env = SandboxEnvironment(
            name="test-env",
            created_at=datetime.now(),
            root_path="/tmp/test-env",
            status=SandboxStatus.CREATED,
            packages_installed=[],
            network_enabled=False,
            cpu_limit=2,
            memory_limit=2048,
            disk_limit=1024,
        )

        self.assertEqual(env.name, "test-env")
        self.assertEqual(env.status, SandboxStatus.CREATED)
        self.assertEqual(env.cpu_limit, 2)
        self.assertEqual(env.memory_limit, 2048)
        self.assertFalse(env.network_enabled)

    def test_to_dict(self):
        """Test converting environment to dictionary."""
        env = SandboxEnvironment(
            name="test-env",
            created_at=datetime(2024, 1, 1, 12, 0, 0),
            root_path="/tmp/test-env",
            status=SandboxStatus.ACTIVE,
            packages_installed=["nginx", "curl"],
        )

        data = env.to_dict()

        self.assertEqual(data["name"], "test-env")
        self.assertEqual(data["status"], "active")
        self.assertIn("nginx", data["packages_installed"])

    def test_from_dict(self):
        """Test creating environment from dictionary."""
        data = {
            "name": "restored-env",
            "created_at": "2024-01-01T12:00:00",
            "root_path": "/tmp/restored-env",
            "status": "testing",
            "packages_installed": '["docker"]',
            "network_enabled": 1,
            "cpu_limit": 4,
            "memory_limit": 4096,
            "disk_limit": 2048,
        }

        env = SandboxEnvironment.from_dict(data)

        self.assertEqual(env.name, "restored-env")
        self.assertEqual(env.status, SandboxStatus.TESTING)
        self.assertTrue(env.network_enabled)
        self.assertEqual(env.cpu_limit, 4)
        self.assertEqual(env.packages_installed, ["docker"])


class TestSandboxManager(unittest.TestCase):
    """Test SandboxManager functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SandboxManager(base_path=self.temp_dir)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_creates_directory(self):
        """Test that initialization creates base directory."""
        self.assertTrue(os.path.exists(self.temp_dir))
        self.assertTrue(os.path.exists(self.manager.db_path))

    def test_init_creates_database(self):
        """Test that database is initialized with correct schema."""
        with sqlite3.connect(self.manager.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

        self.assertIn("sandboxes", tables)
        self.assertIn("sandbox_tests", tables)

    def test_create_environment(self):
        """Test creating a sandbox environment."""
        env = self.manager.create("test-env")

        self.assertEqual(env.name, "test-env")
        self.assertEqual(env.status, SandboxStatus.CREATED)
        self.assertTrue(os.path.exists(env.root_path))
        self.assertTrue(os.path.exists(os.path.join(env.root_path, "home")))
        self.assertTrue(os.path.exists(os.path.join(env.root_path, "var")))
        self.assertTrue(os.path.exists(os.path.join(env.root_path, "logs")))

    def test_create_environment_with_options(self):
        """Test creating environment with custom options."""
        env = self.manager.create(
            name="custom-env",
            network=True,
            cpu=4,
            memory=4096,
            disk=2048,
        )

        self.assertTrue(env.network_enabled)
        self.assertEqual(env.cpu_limit, 4)
        self.assertEqual(env.memory_limit, 4096)
        self.assertEqual(env.disk_limit, 2048)

    def test_create_duplicate_fails(self):
        """Test that creating duplicate environment fails."""
        self.manager.create("dup-env")

        with self.assertRaises(ValueError) as ctx:
            self.manager.create("dup-env")

        self.assertIn("already exists", str(ctx.exception))

    def test_create_invalid_name_fails(self):
        """Test that invalid names are rejected."""
        invalid_names = ["", "test env", "test/env", "test@env"]

        for name in invalid_names:
            with self.assertRaises(ValueError):
                self.manager.create(name)

    def test_create_firejail_profile(self):
        """Test that Firejail profile is created."""
        env = self.manager.create("profile-test")

        self.assertTrue(os.path.exists(env.firejail_profile))

        with open(env.firejail_profile) as f:
            content = f.read()

        self.assertIn("profile-test", content)
        self.assertIn("private", content)
        self.assertIn("seccomp", content)

    def test_get_environment(self):
        """Test retrieving an environment."""
        self.manager.create("get-test")

        env = self.manager.get_environment("get-test")

        self.assertIsNotNone(env)
        self.assertEqual(env.name, "get-test")

    def test_get_nonexistent_environment(self):
        """Test retrieving non-existent environment returns None."""
        env = self.manager.get_environment("nonexistent")
        self.assertIsNone(env)

    def test_list_environments(self):
        """Test listing all environments."""
        self.manager.create("env-1")
        self.manager.create("env-2")
        self.manager.create("env-3")

        environments = self.manager.list_environments()

        self.assertEqual(len(environments), 3)
        names = {e.name for e in environments}
        self.assertEqual(names, {"env-1", "env-2", "env-3"})

    def test_list_empty(self):
        """Test listing when no environments exist."""
        environments = self.manager.list_environments()
        self.assertEqual(len(environments), 0)

    def test_destroy_environment(self):
        """Test destroying an environment."""
        env = self.manager.create("destroy-test")
        root_path = env.root_path

        result = self.manager.destroy("destroy-test")

        self.assertTrue(result)
        self.assertFalse(os.path.exists(root_path))
        self.assertIsNone(self.manager.get_environment("destroy-test"))

    def test_destroy_nonexistent(self):
        """Test destroying non-existent environment."""
        result = self.manager.destroy("nonexistent")
        self.assertFalse(result)

    @patch.object(SandboxManager, "_build_sandbox_command")
    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_install_package_dry_run(self, mock_execute, mock_build_cmd):
        """Test dry-run package installation."""
        self.manager.create("install-test")

        result = self.manager.install_package("install-test", "nginx", dry_run=True)

        self.assertIn("[DRY-RUN]", result.stdout)
        mock_execute.assert_not_called()

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_install_package_success(self, mock_execute):
        """Test successful package installation."""
        mock_execute.return_value = ExecutionResult(
            command="apt-get install -y nginx",
            exit_code=0,
            stdout="Package installed",
        )

        self.manager.create("install-test")
        result = self.manager.install_package("install-test", "nginx", dry_run=False)

        self.assertTrue(result.success)

        # Check package was tracked
        env = self.manager.get_environment("install-test")
        self.assertIn("nginx", env.packages_installed)

    def test_install_package_not_found(self):
        """Test installing in non-existent sandbox."""
        with self.assertRaises(ValueError) as ctx:
            self.manager.install_package("nonexistent", "nginx")

        self.assertIn("not found", str(ctx.exception))

    def test_list_packages(self):
        """Test listing installed packages."""
        env = self.manager.create("pkg-list-test")
        env.packages_installed = ["nginx", "curl", "wget"]
        self.manager._save_environment(env)

        packages = self.manager.list_packages("pkg-list-test")

        self.assertEqual(packages, ["nginx", "curl", "wget"])

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_promote_to_system_dry_run(self, mock_execute):
        """Test dry-run promotion."""
        env = self.manager.create("promote-test")
        env.packages_installed = ["nginx", "curl"]
        self.manager._save_environment(env)

        result = self.manager.promote_to_system("promote-test", dry_run=True)

        self.assertTrue(result.success)
        self.assertTrue(result.preview)
        self.assertIn("nginx", result.packages)
        mock_execute.assert_not_called()

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_promote_to_system_success(self, mock_execute):
        """Test successful promotion."""
        mock_execute.return_value = ExecutionResult(
            command="sudo apt-get install -y nginx",
            exit_code=0,
        )

        env = self.manager.create("promote-test")
        env.packages_installed = ["nginx"]
        self.manager._save_environment(env)

        result = self.manager.promote_to_system("promote-test", dry_run=False)

        self.assertTrue(result.success)
        self.assertEqual(result.packages, ["nginx"])

        # Check status was updated
        env = self.manager.get_environment("promote-test")
        self.assertEqual(env.status, SandboxStatus.PROMOTED)

    def test_promote_empty_sandbox(self):
        """Test promoting sandbox with no packages."""
        self.manager.create("empty-promote")

        result = self.manager.promote_to_system("empty-promote")

        self.assertFalse(result.success)
        self.assertIn("No packages", result.message)

    def test_promote_nonexistent(self):
        """Test promoting non-existent sandbox."""
        result = self.manager.promote_to_system("nonexistent")

        self.assertFalse(result.success)
        self.assertIn("not found", result.message)

    def test_get_status(self):
        """Test getting detailed status."""
        env = self.manager.create("status-test")
        env.packages_installed = ["nginx"]
        self.manager._save_environment(env)

        status = self.manager.get_status("status-test")

        self.assertEqual(status["name"], "status-test")
        self.assertEqual(status["package_count"], 1)
        self.assertIn("limits", status)
        self.assertIn("firejail_available", status)

    def test_get_status_nonexistent(self):
        """Test getting status of non-existent sandbox."""
        status = self.manager.get_status("nonexistent")
        self.assertIn("error", status)

    def test_save_test_result(self):
        """Test saving test results."""
        self.manager.create("test-results")

        self.manager.save_test_result(
            "test-results",
            "Functional Test",
            True,
            "Package works",
            "nginx",
        )

        status = self.manager.get_status("test-results")
        self.assertEqual(len(status["recent_tests"]), 1)
        self.assertEqual(status["recent_tests"][0]["test_name"], "Functional Test")


class TestSandboxTester(unittest.TestCase):
    """Test SandboxTester functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.manager = SandboxManager(base_path=self.temp_dir)
        self.tester = SandboxTester(self.manager)

    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_tester_initialization(self):
        """Test tester is properly initialized."""
        self.assertEqual(self.tester.manager, self.manager)
        self.assertIsNotNone(self.tester.executor)

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_functional_test_success(self, mock_execute):
        """Test successful functional test."""
        mock_execute.return_value = ExecutionResult(
            command="nginx --version",
            exit_code=0,
            stdout="nginx version: 1.18.0",
        )

        self.manager.create("func-test")

        result = self.tester.test_package_functional("func-test", "nginx")

        self.assertTrue(result.passed)
        self.assertIn("functional", result.message.lower())

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_functional_test_failure(self, mock_execute):
        """Test failed functional test."""
        mock_execute.return_value = ExecutionResult(
            command="nonexistent --version",
            exit_code=1,
            stderr="command not found",
        )

        self.manager.create("func-test-fail")

        result = self.tester.test_package_functional("func-test-fail", "nonexistent")

        self.assertFalse(result.passed)

    def test_functional_test_no_sandbox(self):
        """Test functional test with non-existent sandbox."""
        result = self.tester.test_package_functional("nonexistent", "nginx")

        self.assertFalse(result.passed)
        self.assertIn("not found", result.message)

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_no_conflicts_success(self, mock_execute):
        """Test successful conflict check."""
        mock_execute.return_value = ExecutionResult(
            command="dpkg --audit",
            exit_code=0,
            stdout="",  # Empty output means no issues
        )

        self.manager.create("conflict-test")

        result = self.tester.test_no_conflicts("conflict-test")

        self.assertTrue(result.passed)
        self.assertIn("No", result.message)

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_dependencies_test(self, mock_execute):
        """Test dependency check."""
        mock_execute.return_value = ExecutionResult(
            command="apt-cache depends nginx",
            exit_code=0,
            stdout="Depends: libc6\nDepends: libpcre3",
        )

        self.manager.create("deps-test")

        result = self.tester.test_dependencies("deps-test", "nginx")

        self.assertTrue(result.passed)
        self.assertIn("satisfied", result.message.lower())

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_performance_test_success(self, mock_execute):
        """Test performance check passes."""
        mock_execute.return_value = ExecutionResult(
            command="nginx --version",
            exit_code=0,
            stdout="nginx version: 1.18.0",
            execution_time=0.5,
        )

        self.manager.create("perf-test")

        result = self.tester.test_performance("perf-test", "nginx", max_startup_time=5.0)

        self.assertTrue(result.passed)
        self.assertIn("acceptable", result.message.lower())

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_run_all_tests(self, mock_execute):
        """Test running full test suite."""
        mock_execute.return_value = ExecutionResult(
            command="test",
            exit_code=0,
            stdout="OK",
        )

        env = self.manager.create("all-tests")
        env.packages_installed = ["nginx"]
        self.manager._save_environment(env)

        results = self.tester.run_all_tests("all-tests")

        self.assertIsInstance(results, TestSuiteResult)
        self.assertEqual(results.sandbox_name, "all-tests")
        self.assertGreater(results.total_tests, 0)

    def test_run_all_tests_no_sandbox(self):
        """Test running tests on non-existent sandbox."""
        results = self.tester.run_all_tests("nonexistent")

        self.assertEqual(results.failed, 1)
        self.assertIn("not found", results.results[0].message)

    @patch("cortex.sandbox.sandbox_executor.SandboxExecutor.execute")
    def test_quick_test(self, mock_execute):
        """Test quick test (functional only)."""
        mock_execute.return_value = ExecutionResult(
            command="nginx --version",
            exit_code=0,
            stdout="nginx version: 1.18.0",
        )

        self.manager.create("quick-test")

        results = self.tester.run_quick_test("quick-test", "nginx")

        self.assertEqual(results.total_tests, 1)
        self.assertTrue(results.results[0].passed)


class TestTestResult(unittest.TestCase):
    """Test TestResult dataclass."""

    def test_create_result(self):
        """Test creating a TestResult."""
        result = TestResult(
            test_name="Functional Test",
            passed=True,
            message="Test passed",
            package_name="nginx",
            duration_seconds=1.5,
        )

        self.assertEqual(result.test_name, "Functional Test")
        self.assertTrue(result.passed)
        self.assertEqual(result.duration_seconds, 1.5)

    def test_to_dict(self):
        """Test converting result to dictionary."""
        result = TestResult(
            test_name="Test",
            passed=False,
            message="Failed",
        )

        data = result.to_dict()

        self.assertEqual(data["test_name"], "Test")
        self.assertFalse(data["passed"])
        self.assertIn("timestamp", data)


class TestTestSuiteResult(unittest.TestCase):
    """Test TestSuiteResult dataclass."""

    def test_all_passed(self):
        """Test all_passed property."""
        result = TestSuiteResult(
            sandbox_name="test",
            total_tests=3,
            passed=3,
            failed=0,
            results=[],
        )

        self.assertTrue(result.all_passed)

    def test_not_all_passed(self):
        """Test all_passed when some fail."""
        result = TestSuiteResult(
            sandbox_name="test",
            total_tests=3,
            passed=2,
            failed=1,
            results=[],
        )

        self.assertFalse(result.all_passed)

    def test_pass_rate(self):
        """Test pass_rate calculation."""
        result = TestSuiteResult(
            sandbox_name="test",
            total_tests=4,
            passed=3,
            failed=1,
            results=[],
        )

        self.assertEqual(result.pass_rate, 75.0)

    def test_pass_rate_zero_tests(self):
        """Test pass_rate with zero tests."""
        result = TestSuiteResult(
            sandbox_name="test",
            total_tests=0,
            passed=0,
            failed=0,
            results=[],
        )

        self.assertEqual(result.pass_rate, 0.0)


class TestPromotionResult(unittest.TestCase):
    """Test PromotionResult dataclass."""

    def test_create_result(self):
        """Test creating a PromotionResult."""
        result = PromotionResult(
            success=True,
            packages=["nginx", "curl"],
            message="Promoted successfully",
        )

        self.assertTrue(result.success)
        self.assertEqual(len(result.packages), 2)

    def test_with_errors(self):
        """Test result with errors."""
        result = PromotionResult(
            success=False,
            packages=[],
            message="Failed",
            errors=["Error 1", "Error 2"],
        )

        self.assertFalse(result.success)
        self.assertEqual(len(result.errors), 2)


if __name__ == "__main__":
    unittest.main()
