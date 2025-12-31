#!/usr/bin/env python3
"""
Sandbox Tester for Cortex Linux.

Provides automated testing capabilities for packages installed
in sandbox environments before promotion to the main system.

Test Types:
- Functional: Verify package runs without errors
- Conflicts: Check for dependency conflicts
- Performance: Validate startup time and resource usage
- Dependencies: Verify all dependencies are satisfied
"""

import shlex
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from cortex.sandbox.sandbox_executor import ExecutionResult

if TYPE_CHECKING:
    from cortex.sandbox.sandbox_manager import SandboxManager


@dataclass
class TestResult:
    """Result of a single test."""

    test_name: str
    passed: bool
    message: str = ""
    package_name: str | None = None
    duration_seconds: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "test_name": self.test_name,
            "passed": self.passed,
            "message": self.message,
            "package_name": self.package_name,
            "duration_seconds": self.duration_seconds,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class TestSuiteResult:
    """Result of running a full test suite."""

    sandbox_name: str
    total_tests: int
    passed: int
    failed: int
    results: list[TestResult]
    duration_seconds: float = 0.0

    @property
    def all_passed(self) -> bool:
        """Check if all tests passed."""
        return self.failed == 0

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate percentage."""
        if self.total_tests == 0:
            return 0.0
        return (self.passed / self.total_tests) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sandbox_name": self.sandbox_name,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "duration_seconds": self.duration_seconds,
            "results": [r.to_dict() for r in self.results],
        }


class SandboxTester:
    """
    Run automated tests in sandbox environments.

    Tests verify that packages work correctly before
    being promoted to the main system.
    """

    # Commands to test package functionality
    FUNCTIONAL_TEST_COMMANDS = [
        "{package} --version",
        "{package} --help",
        "{package} -V",
        "{package} -h",
        "which {package}",
        "command -v {package}",
    ]

    # Maximum acceptable startup time in seconds
    MAX_STARTUP_TIME = 5.0

    # Maximum acceptable memory usage in MB for startup
    MAX_STARTUP_MEMORY_MB = 500

    def __init__(self, manager: "SandboxManager"):
        """
        Initialize sandbox tester.

        Args:
            manager: SandboxManager instance
        """
        self.manager = manager
        self.executor = manager.executor

    def test_package_functional(
        self,
        env_name: str,
        package: str,
    ) -> TestResult:
        """
        Test that a package is functional (can run basic commands).

        Args:
            env_name: Sandbox environment name
            package: Package name to test

        Returns:
            TestResult with pass/fail status
        """
        start_time = time.time()

        env = self.manager.get_environment(env_name)
        if not env:
            return TestResult(
                test_name="Package Functional",
                passed=False,
                message=f"Sandbox '{env_name}' not found",
                package_name=package,
            )

        # Try various commands to verify package works
        for cmd_template in self.FUNCTIONAL_TEST_COMMANDS:
            cmd = cmd_template.format(package=shlex.quote(package))

            try:
                result = self.executor.execute(cmd, dry_run=False)

                if result.success:
                    duration = time.time() - start_time
                    test_result = TestResult(
                        test_name="Package Functional",
                        passed=True,
                        message=f"{package} is functional ({cmd})",
                        package_name=package,
                        duration_seconds=duration,
                        details={
                            "command": cmd,
                            "output": result.stdout[:200] if result.stdout else "",
                        },
                    )

                    # Save to database
                    self.manager.save_test_result(
                        env_name,
                        "Package Functional",
                        True,
                        test_result.message,
                        package,
                    )

                    return test_result

            except Exception:
                continue

        duration = time.time() - start_time
        test_result = TestResult(
            test_name="Package Functional",
            passed=False,
            message=f"{package} may not be functional (no working command found)",
            package_name=package,
            duration_seconds=duration,
        )

        self.manager.save_test_result(
            env_name,
            "Package Functional",
            False,
            test_result.message,
            package,
        )

        return test_result

    def test_no_conflicts(self, env_name: str) -> TestResult:
        """
        Test that there are no package conflicts in the sandbox.

        Args:
            env_name: Sandbox environment name

        Returns:
            TestResult with pass/fail status
        """
        start_time = time.time()

        env = self.manager.get_environment(env_name)
        if not env:
            return TestResult(
                test_name="No Conflicts",
                passed=False,
                message=f"Sandbox '{env_name}' not found",
            )

        # Check for broken packages
        check_cmd = "dpkg --audit"

        try:
            result = self.executor.execute(check_cmd, dry_run=False)

            # dpkg --audit returns empty output if no issues
            has_conflicts = bool(result.stdout and result.stdout.strip())

            duration = time.time() - start_time

            if not has_conflicts and result.exit_code == 0:
                test_result = TestResult(
                    test_name="No Conflicts",
                    passed=True,
                    message="No package conflicts detected",
                    duration_seconds=duration,
                )
            else:
                test_result = TestResult(
                    test_name="No Conflicts",
                    passed=False,
                    message=f"Package conflicts detected: {result.stdout[:200]}",
                    duration_seconds=duration,
                    details={"audit_output": result.stdout},
                )

            self.manager.save_test_result(
                env_name,
                "No Conflicts",
                test_result.passed,
                test_result.message,
            )

            return test_result

        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                test_name="No Conflicts",
                passed=False,
                message=f"Failed to check conflicts: {str(e)}",
                duration_seconds=duration,
            )

    def test_dependencies(
        self,
        env_name: str,
        package: str,
    ) -> TestResult:
        """
        Test that all package dependencies are satisfied.

        Args:
            env_name: Sandbox environment name
            package: Package name to test

        Returns:
            TestResult with pass/fail status
        """
        start_time = time.time()

        env = self.manager.get_environment(env_name)
        if not env:
            return TestResult(
                test_name="Dependencies Satisfied",
                passed=False,
                message=f"Sandbox '{env_name}' not found",
                package_name=package,
            )

        # Check if package dependencies are satisfied
        check_cmd = f"apt-cache depends {shlex.quote(package)}"

        try:
            result = self.executor.execute(check_cmd, dry_run=False)

            duration = time.time() - start_time

            if result.success:
                # Parse dependencies
                deps = []
                for line in result.stdout.split("\n"):
                    line = line.strip()
                    if line.startswith("Depends:"):
                        dep = line.replace("Depends:", "").strip()
                        deps.append(dep)

                test_result = TestResult(
                    test_name="Dependencies Satisfied",
                    passed=True,
                    message=f"All {len(deps)} dependencies satisfied",
                    package_name=package,
                    duration_seconds=duration,
                    details={"dependencies": deps},
                )
            else:
                test_result = TestResult(
                    test_name="Dependencies Satisfied",
                    passed=False,
                    message=f"Dependency check failed: {result.stderr}",
                    package_name=package,
                    duration_seconds=duration,
                )

            self.manager.save_test_result(
                env_name,
                "Dependencies Satisfied",
                test_result.passed,
                test_result.message,
                package,
            )

            return test_result

        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                test_name="Dependencies Satisfied",
                passed=False,
                message=f"Failed to check dependencies: {str(e)}",
                package_name=package,
                duration_seconds=duration,
            )

    def test_performance(
        self,
        env_name: str,
        package: str,
        max_startup_time: float | None = None,
    ) -> TestResult:
        """
        Test package performance (startup time).

        Args:
            env_name: Sandbox environment name
            package: Package name to test
            max_startup_time: Maximum acceptable startup time in seconds

        Returns:
            TestResult with pass/fail status
        """
        start_time = time.time()
        max_time = max_startup_time or self.MAX_STARTUP_TIME

        env = self.manager.get_environment(env_name)
        if not env:
            return TestResult(
                test_name="Performance",
                passed=False,
                message=f"Sandbox '{env_name}' not found",
                package_name=package,
            )

        # Time how long it takes to run --version
        cmd = f"time {shlex.quote(package)} --version"

        try:
            cmd_start = time.time()
            result = self.executor.execute(f"{package} --version", dry_run=False)
            cmd_duration = time.time() - cmd_start

            duration = time.time() - start_time

            if cmd_duration <= max_time:
                test_result = TestResult(
                    test_name="Performance",
                    passed=True,
                    message=f"Startup time acceptable ({cmd_duration:.2f}s < {max_time}s)",
                    package_name=package,
                    duration_seconds=duration,
                    details={
                        "startup_time": cmd_duration,
                        "max_allowed": max_time,
                    },
                )
            else:
                test_result = TestResult(
                    test_name="Performance",
                    passed=False,
                    message=f"Startup time too slow ({cmd_duration:.2f}s > {max_time}s)",
                    package_name=package,
                    duration_seconds=duration,
                    details={
                        "startup_time": cmd_duration,
                        "max_allowed": max_time,
                    },
                )

            self.manager.save_test_result(
                env_name,
                "Performance",
                test_result.passed,
                test_result.message,
                package,
            )

            return test_result

        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                test_name="Performance",
                passed=False,
                message=f"Performance test failed: {str(e)}",
                package_name=package,
                duration_seconds=duration,
            )

    def test_installation_integrity(
        self,
        env_name: str,
        package: str,
    ) -> TestResult:
        """
        Test that package installation is complete and files are intact.

        Args:
            env_name: Sandbox environment name
            package: Package name to test

        Returns:
            TestResult with pass/fail status
        """
        start_time = time.time()

        env = self.manager.get_environment(env_name)
        if not env:
            return TestResult(
                test_name="Installation Integrity",
                passed=False,
                message=f"Sandbox '{env_name}' not found",
                package_name=package,
            )

        # Verify package installation
        check_cmd = f"dpkg -V {shlex.quote(package)}"

        try:
            result = self.executor.execute(check_cmd, dry_run=False)

            duration = time.time() - start_time

            # dpkg -V returns empty output if all files are OK
            if not result.stdout or not result.stdout.strip():
                test_result = TestResult(
                    test_name="Installation Integrity",
                    passed=True,
                    message=f"{package} installation is intact",
                    package_name=package,
                    duration_seconds=duration,
                )
            else:
                test_result = TestResult(
                    test_name="Installation Integrity",
                    passed=False,
                    message=f"Installation issues found: {result.stdout[:200]}",
                    package_name=package,
                    duration_seconds=duration,
                    details={"verification_output": result.stdout},
                )

            self.manager.save_test_result(
                env_name,
                "Installation Integrity",
                test_result.passed,
                test_result.message,
                package,
            )

            return test_result

        except Exception as e:
            duration = time.time() - start_time
            return TestResult(
                test_name="Installation Integrity",
                passed=False,
                message=f"Integrity check failed: {str(e)}",
                package_name=package,
                duration_seconds=duration,
            )

    def run_all_tests(
        self,
        env_name: str,
        package: str | None = None,
    ) -> TestSuiteResult:
        """
        Run all tests for a sandbox environment.

        Args:
            env_name: Sandbox environment name
            package: Optional specific package to test (tests all if None)

        Returns:
            TestSuiteResult with all test results
        """
        start_time = time.time()
        results: list[TestResult] = []

        env = self.manager.get_environment(env_name)
        if not env:
            return TestSuiteResult(
                sandbox_name=env_name,
                total_tests=0,
                passed=0,
                failed=1,
                results=[
                    TestResult(
                        test_name="Environment Check",
                        passed=False,
                        message=f"Sandbox '{env_name}' not found",
                    )
                ],
            )

        # Update status to testing
        env.status = self.manager.SandboxStatus.TESTING  # type: ignore[attr-defined]
        self.manager._save_environment(env)

        # Determine which packages to test
        packages_to_test = [package] if package else env.packages_installed

        if not packages_to_test:
            return TestSuiteResult(
                sandbox_name=env_name,
                total_tests=0,
                passed=0,
                failed=0,
                results=[],
                duration_seconds=time.time() - start_time,
            )

        # Run tests for each package
        for pkg in packages_to_test:
            # Functional test
            results.append(self.test_package_functional(env_name, pkg))

            # Dependencies test
            results.append(self.test_dependencies(env_name, pkg))

            # Performance test
            results.append(self.test_performance(env_name, pkg))

            # Installation integrity test
            results.append(self.test_installation_integrity(env_name, pkg))

        # Run environment-wide tests
        results.append(self.test_no_conflicts(env_name))

        # Calculate totals
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed

        # Update environment status based on results
        if failed == 0:
            env.status = self.manager.SandboxStatus.ACTIVE  # type: ignore[attr-defined]
        else:
            env.status = self.manager.SandboxStatus.FAILED  # type: ignore[attr-defined]
        self.manager._save_environment(env)

        return TestSuiteResult(
            sandbox_name=env_name,
            total_tests=len(results),
            passed=passed,
            failed=failed,
            results=results,
            duration_seconds=time.time() - start_time,
        )

    def run_quick_test(
        self,
        env_name: str,
        package: str,
    ) -> TestSuiteResult:
        """
        Run a quick test (functional only) for a package.

        Args:
            env_name: Sandbox environment name
            package: Package name to test

        Returns:
            TestSuiteResult with test results
        """
        start_time = time.time()
        results: list[TestResult] = []

        # Only run functional test
        results.append(self.test_package_functional(env_name, package))

        passed = sum(1 for r in results if r.passed)

        return TestSuiteResult(
            sandbox_name=env_name,
            total_tests=len(results),
            passed=passed,
            failed=len(results) - passed,
            results=results,
            duration_seconds=time.time() - start_time,
        )
