#!/usr/bin/env python3
"""
Sandbox Environment Manager for Cortex Linux.

Manages isolated sandbox environments for testing packages before
promoting them to the main system. Uses Firejail for isolation.

Features:
- Create/destroy isolated sandbox environments
- Install packages in sandboxes with Firejail isolation
- List and manage multiple sandbox environments
- Promote tested packages to main system
- SQLite-backed persistent storage
"""

import json
import os
import shlex
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from cortex.sandbox.sandbox_executor import ExecutionResult, SandboxExecutor


class SandboxStatus(Enum):
    """Status of a sandbox environment."""

    CREATED = "created"
    ACTIVE = "active"
    TESTING = "testing"
    PROMOTED = "promoted"
    FAILED = "failed"
    CLEANED = "cleaned"


@dataclass
class SandboxEnvironment:
    """Represents a sandbox environment."""

    name: str
    created_at: datetime
    root_path: str
    status: SandboxStatus = SandboxStatus.CREATED
    packages_installed: list[str] = field(default_factory=list)
    network_enabled: bool = False
    cpu_limit: int = 2
    memory_limit: int = 2048  # MB
    disk_limit: int = 1024  # MB
    firejail_profile: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "root_path": self.root_path,
            "status": self.status.value,
            "packages_installed": json.dumps(self.packages_installed),
            "network_enabled": self.network_enabled,
            "cpu_limit": self.cpu_limit,
            "memory_limit": self.memory_limit,
            "disk_limit": self.disk_limit,
            "firejail_profile": self.firejail_profile,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SandboxEnvironment":
        """Create from dictionary."""
        packages = data.get("packages_installed", "[]")
        if isinstance(packages, str):
            packages = json.loads(packages)

        return cls(
            name=data["name"],
            created_at=datetime.fromisoformat(data["created_at"]),
            root_path=data["root_path"],
            status=SandboxStatus(data.get("status", "created")),
            packages_installed=packages,
            network_enabled=bool(data.get("network_enabled", False)),
            cpu_limit=int(data.get("cpu_limit", 2)),
            memory_limit=int(data.get("memory_limit", 2048)),
            disk_limit=int(data.get("disk_limit", 1024)),
            firejail_profile=data.get("firejail_profile", ""),
        )


@dataclass
class PromotionResult:
    """Result of promoting packages to main system."""

    success: bool
    packages: list[str]
    preview: bool = False
    message: str = ""
    errors: list[str] = field(default_factory=list)


class SandboxManager:
    """
    Manages sandbox environment lifecycle.

    Provides functionality to:
    - Create isolated sandbox environments
    - Install packages in sandboxes
    - List and manage environments
    - Promote packages to main system
    - Clean up sandbox environments
    """

    FIREJAIL_PROFILE_TEMPLATE = """# Cortex Sandbox Profile for {name}
# Auto-generated - do not edit manually

# Include base profile
include /etc/firejail/default.profile

# Private directories (isolated)
private {home_path}
private-tmp
private-dev

# Resource limits
rlimit-as {memory_bytes}
rlimit-fsize {disk_bytes}

# Network configuration
{network_rule}

# Security hardening
caps.drop all
seccomp
noroot
no-new-privs

# Allow package management
whitelist /var/cache/apt
whitelist /var/lib/apt
whitelist /var/lib/dpkg
read-only /etc/apt
"""

    def __init__(self, base_path: str | None = None):
        """
        Initialize sandbox manager.

        Args:
            base_path: Base directory for sandbox environments.
                      Defaults to ~/.cortex/sandboxes
        """
        self.base_path = os.path.expanduser(base_path or "~/.cortex/sandboxes")
        self.db_path = os.path.join(self.base_path, "sandboxes.db")
        self.executor = SandboxExecutor()

        # Ensure base directory exists
        os.makedirs(self.base_path, mode=0o700, exist_ok=True)

        # Initialize database
        self._init_database()

    def _init_database(self) -> None:
        """Initialize SQLite database for sandbox metadata."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Sandboxes table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sandboxes (
                    name TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    root_path TEXT NOT NULL,
                    status TEXT DEFAULT 'created',
                    packages_installed TEXT DEFAULT '[]',
                    network_enabled INTEGER DEFAULT 0,
                    cpu_limit INTEGER DEFAULT 2,
                    memory_limit INTEGER DEFAULT 2048,
                    disk_limit INTEGER DEFAULT 1024,
                    firejail_profile TEXT DEFAULT ''
                )
            """
            )

            # Test results table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sandbox_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sandbox_name TEXT NOT NULL,
                    test_name TEXT NOT NULL,
                    package_name TEXT,
                    passed INTEGER NOT NULL,
                    message TEXT,
                    run_at TEXT NOT NULL,
                    FOREIGN KEY (sandbox_name) REFERENCES sandboxes(name)
                )
            """
            )

            conn.commit()

    def _save_environment(self, env: SandboxEnvironment) -> None:
        """Save environment to database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            data = env.to_dict()

            cursor.execute(
                """
                INSERT OR REPLACE INTO sandboxes
                (name, created_at, root_path, status, packages_installed,
                 network_enabled, cpu_limit, memory_limit, disk_limit, firejail_profile)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    data["name"],
                    data["created_at"],
                    data["root_path"],
                    data["status"],
                    data["packages_installed"],
                    1 if data["network_enabled"] else 0,
                    data["cpu_limit"],
                    data["memory_limit"],
                    data["disk_limit"],
                    data["firejail_profile"],
                ),
            )
            conn.commit()

    def _load_environment(self, name: str) -> SandboxEnvironment | None:
        """Load environment from database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sandboxes WHERE name = ?", (name,))
            row = cursor.fetchone()

            if row:
                return SandboxEnvironment.from_dict(dict(row))
            return None

    def _delete_environment(self, name: str) -> None:
        """Delete environment from database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sandbox_tests WHERE sandbox_name = ?", (name,))
            cursor.execute("DELETE FROM sandboxes WHERE name = ?", (name,))
            conn.commit()

    def _generate_firejail_profile(self, env: SandboxEnvironment) -> str:
        """Generate Firejail profile for sandbox."""
        memory_bytes = env.memory_limit * 1024 * 1024
        disk_bytes = env.disk_limit * 1024 * 1024
        network_rule = "net none" if not env.network_enabled else "# Network enabled"

        return self.FIREJAIL_PROFILE_TEMPLATE.format(
            name=env.name,
            home_path=os.path.join(env.root_path, "home"),
            memory_bytes=memory_bytes,
            disk_bytes=disk_bytes,
            network_rule=network_rule,
        )

    def create(
        self,
        name: str,
        network: bool = False,
        cpu: int = 2,
        memory: int = 2048,
        disk: int = 1024,
    ) -> SandboxEnvironment:
        """
        Create a new sandbox environment.

        Args:
            name: Name for the sandbox environment
            network: Whether to enable network access
            cpu: CPU cores limit
            memory: Memory limit in MB
            disk: Disk limit in MB

        Returns:
            Created SandboxEnvironment

        Raises:
            ValueError: If sandbox with name already exists
            OSError: If directory creation fails
        """
        # Check if already exists
        existing = self._load_environment(name)
        if existing:
            raise ValueError(f"Sandbox '{name}' already exists")

        # Validate name (alphanumeric and hyphens only)
        if not name or not all(c.isalnum() or c == "-" for c in name):
            raise ValueError("Sandbox name must be alphanumeric with hyphens only")

        # Create directory structure
        sandbox_root = os.path.join(self.base_path, name)
        home_path = os.path.join(sandbox_root, "home")
        var_path = os.path.join(sandbox_root, "var")
        logs_path = os.path.join(sandbox_root, "logs")

        os.makedirs(home_path, mode=0o700, exist_ok=True)
        os.makedirs(var_path, mode=0o700, exist_ok=True)
        os.makedirs(logs_path, mode=0o700, exist_ok=True)

        # Create environment
        env = SandboxEnvironment(
            name=name,
            created_at=datetime.now(),
            root_path=sandbox_root,
            status=SandboxStatus.CREATED,
            packages_installed=[],
            network_enabled=network,
            cpu_limit=cpu,
            memory_limit=memory,
            disk_limit=disk,
        )

        # Generate and save Firejail profile
        profile_path = os.path.join(sandbox_root, "firejail.profile")
        env.firejail_profile = profile_path

        profile_content = self._generate_firejail_profile(env)
        with open(profile_path, "w") as f:
            f.write(profile_content)

        # Save to database
        self._save_environment(env)

        return env

    def get_environment(self, name: str) -> SandboxEnvironment | None:
        """
        Get a sandbox environment by name.

        Args:
            name: Sandbox name

        Returns:
            SandboxEnvironment or None if not found
        """
        return self._load_environment(name)

    def list_environments(self) -> list[SandboxEnvironment]:
        """
        List all sandbox environments.

        Returns:
            List of SandboxEnvironment objects
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sandboxes ORDER BY created_at DESC")
            rows = cursor.fetchall()

            return [SandboxEnvironment.from_dict(dict(row)) for row in rows]

    def destroy(self, name: str) -> bool:
        """
        Destroy a sandbox environment.

        Args:
            name: Sandbox name to destroy

        Returns:
            True if successfully destroyed, False if not found
        """
        env = self._load_environment(name)
        if not env:
            return False

        # Remove directory tree
        if os.path.exists(env.root_path):
            shutil.rmtree(env.root_path, ignore_errors=True)

        # Remove from database
        self._delete_environment(name)

        return True

    def _build_sandbox_command(self, env: SandboxEnvironment, command: str) -> list[str]:
        """
        Build command with sandbox-specific Firejail profile for testing.

        Args:
            env: Sandbox environment
            command: Command to execute

        Returns:
            List of command parts for subprocess
        """
        if not self.executor.firejail_path:
            # Fallback without Firejail
            return shlex.split(command)

        memory_bytes = env.memory_limit * 1024 * 1024

        firejail_cmd = [
            self.executor.firejail_path,
            "--quiet",
            f"--private={os.path.join(env.root_path, 'home')}",
            "--private-tmp",
            f"--cpu={env.cpu_limit}",
            f"--rlimit-as={memory_bytes}",
            "--noroot",
            "--caps.drop=all",
            "--seccomp",
        ]

        # Network configuration
        if not env.network_enabled:
            firejail_cmd.append("--net=none")

        # Add the actual command
        firejail_cmd.extend(shlex.split(command))

        return firejail_cmd

    def _build_install_command(self, env: SandboxEnvironment, command: str) -> list[str]:
        """
        Build command for package installation (requires elevated privileges).

        MAINTAINER NOTE - Why Firejail Cannot Be Used for Package Installation:
        ========================================================================
        Firejail's security model is fundamentally incompatible with `sudo`:

        1. --noroot: Sets "no new privileges" flag, blocking sudo entirely
        2. --seccomp: Also sets "no new privileges" flag
        3. --caps.drop=all: Drops capabilities needed for privilege escalation

        Error we encountered:
            "sudo: The 'no new privileges' flag is set, which prevents sudo
             from running as root."

        This is BY DESIGN - Firejail prevents privilege escalation for security.
        But package installation (apt-get install) REQUIRES root privileges.

        RECOMMENDED SOLUTION - Docker/Podman:
        =====================================
        Docker containers can run as root internally while being isolated:
        - `docker run --rm ubuntu apt-get install -y curl` works perfectly
        - Full filesystem isolation (not just /home like Firejail)
        - Can snapshot/commit container state for true "promote to system"
        - Network isolation without blocking apt downloads
        - Proper cleanup by removing container

        Current workaround: Skip Firejail for install, use it only for testing.
        This tracks packages but doesn't provide true installation isolation.

        Args:
            env: Sandbox environment
            command: Command to execute

        Returns:
            List of command parts for subprocess
        """
        # For installation, skip Firejail entirely since sudo is incompatible
        # with Firejail's "no new privileges" security model.
        # The package is tracked in the sandbox for testing/promotion.
        return shlex.split(command)

    def install_package(
        self,
        env_name: str,
        package: str,
        dry_run: bool = False,
    ) -> ExecutionResult:
        """
        Install a package in a sandbox environment.

        Note: Package installation requires root access. The package is installed
        on the system but tracked as part of this sandbox environment. Use
        'promote' to finalize or 'cleanup' to remove.

        Args:
            env_name: Sandbox environment name
            package: Package name to install
            dry_run: If True, only preview the installation

        Returns:
            ExecutionResult from the installation

        Raises:
            ValueError: If sandbox not found
        """
        env = self._load_environment(env_name)
        if not env:
            raise ValueError(f"Sandbox '{env_name}' not found")

        # Update status
        env.status = SandboxStatus.ACTIVE
        self._save_environment(env)

        # Build installation command
        install_cmd = f"sudo apt-get install -y {shlex.quote(package)}"

        if dry_run:
            # For dry run, show what would be executed
            cmd_parts = self._build_install_command(env, install_cmd)
            preview = " ".join(shlex.quote(arg) for arg in cmd_parts)

            return ExecutionResult(
                command=install_cmd,
                exit_code=0,
                stdout=f"[DRY-RUN] Would execute in sandbox '{env_name}':\n{preview}",
                preview=preview,
            )

        # Execute without Firejail (sudo is incompatible with Firejail's security model)
        # Use the executor's execute method with use_sandbox=False
        result = self.executor.execute(
            install_cmd,
            dry_run=False,
            enable_rollback=True,
            use_sandbox=False,  # Skip Firejail for sudo commands
        )

        # If successful, track the package
        if result.success:
            if package not in env.packages_installed:
                env.packages_installed.append(package)
                self._save_environment(env)

        return result

    def remove_package(self, env_name: str, package: str) -> ExecutionResult:
        """
        Remove a package from a sandbox environment.

        Args:
            env_name: Sandbox environment name
            package: Package name to remove

        Returns:
            ExecutionResult from the removal
        """
        env = self._load_environment(env_name)
        if not env:
            raise ValueError(f"Sandbox '{env_name}' not found")

        # Build removal command
        remove_cmd = f"apt-get remove -y {shlex.quote(package)}"

        result = self.executor.execute(
            f"sudo {remove_cmd}",
            dry_run=False,
            enable_rollback=True,
        )

        # If successful, remove from tracking
        if result.success and package in env.packages_installed:
            env.packages_installed.remove(package)
            self._save_environment(env)

        return result

    def list_packages(self, env_name: str) -> list[str]:
        """
        List packages installed in a sandbox.

        Args:
            env_name: Sandbox environment name

        Returns:
            List of package names
        """
        env = self._load_environment(env_name)
        if not env:
            raise ValueError(f"Sandbox '{env_name}' not found")

        return list(env.packages_installed)

    def promote_to_system(
        self,
        env_name: str,
        dry_run: bool = False,
    ) -> PromotionResult:
        """
        Promote sandbox packages to the main system.

        Args:
            env_name: Sandbox environment name
            dry_run: If True, only preview what would be installed

        Returns:
            PromotionResult with details
        """
        env = self._load_environment(env_name)
        if not env:
            return PromotionResult(
                success=False,
                packages=[],
                message=f"Sandbox '{env_name}' not found",
            )

        if not env.packages_installed:
            return PromotionResult(
                success=False,
                packages=[],
                message=f"No packages installed in sandbox '{env_name}'",
            )

        packages = list(env.packages_installed)

        if dry_run:
            return PromotionResult(
                success=True,
                packages=packages,
                preview=True,
                message=f"Would install on main system: {', '.join(packages)}",
            )

        # Install packages on main system (not sandboxed)
        errors = []
        successful = []

        for package in packages:
            cmd = f"sudo apt-get install -y {shlex.quote(package)}"
            result = self.executor.execute(cmd, dry_run=False)

            if result.success:
                successful.append(package)
            else:
                errors.append(f"{package}: {result.stderr}")

        # Update status
        if errors:
            env.status = SandboxStatus.FAILED
        else:
            env.status = SandboxStatus.PROMOTED
        self._save_environment(env)

        return PromotionResult(
            success=len(errors) == 0,
            packages=successful,
            message=(
                f"Installed {len(successful)} package(s) on main system"
                if successful
                else "No packages installed"
            ),
            errors=errors,
        )

    def get_status(self, env_name: str) -> dict[str, Any]:
        """
        Get detailed status of a sandbox environment.

        Args:
            env_name: Sandbox environment name

        Returns:
            Dictionary with status information
        """
        env = self._load_environment(env_name)
        if not env:
            return {"error": f"Sandbox '{env_name}' not found"}

        # Get test results
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT test_name, package_name, passed, message, run_at
                FROM sandbox_tests
                WHERE sandbox_name = ?
                ORDER BY run_at DESC
                LIMIT 10
            """,
                (env_name,),
            )
            tests = [dict(row) for row in cursor.fetchall()]

        # Calculate disk usage
        disk_usage = 0
        if os.path.exists(env.root_path):
            for dirpath, dirnames, filenames in os.walk(env.root_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        disk_usage += os.path.getsize(filepath)
                    except OSError:
                        pass

        return {
            "name": env.name,
            "status": env.status.value,
            "created_at": env.created_at.isoformat(),
            "root_path": env.root_path,
            "packages_installed": env.packages_installed,
            "package_count": len(env.packages_installed),
            "network_enabled": env.network_enabled,
            "limits": {
                "cpu": env.cpu_limit,
                "memory_mb": env.memory_limit,
                "disk_mb": env.disk_limit,
            },
            "disk_usage_mb": round(disk_usage / (1024 * 1024), 2),
            "firejail_available": self.executor.is_firejail_available(),
            "recent_tests": tests,
        }

    def save_test_result(
        self,
        env_name: str,
        test_name: str,
        passed: bool,
        message: str = "",
        package_name: str | None = None,
    ) -> None:
        """
        Save a test result to the database.

        Args:
            env_name: Sandbox environment name
            test_name: Name of the test
            passed: Whether the test passed
            message: Optional message
            package_name: Optional package being tested
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sandbox_tests
                (sandbox_name, test_name, package_name, passed, message, run_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    env_name,
                    test_name,
                    package_name,
                    1 if passed else 0,
                    message,
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
