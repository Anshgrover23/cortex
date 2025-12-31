# Cortex Sandbox Environments - Implementation Plan

## Overview

This document outlines the implementation plan for the `cortex sandbox` CLI feature that allows testing packages in isolated sandbox environments before promoting them to the main system.

**Issue Requirements:**
- Create isolated sandbox environments
- Install packages in sandbox
- Run tests in sandbox
- Validate functionality
- Promote to main system
- Cleanup sandbox
- Unit tests included (>80% coverage)

## Existing Infrastructure Analysis

### Current Firejail Implementation

The project already has a robust Firejail-based sandboxing system in [cortex/sandbox/sandbox_executor.py](cortex/sandbox/sandbox_executor.py):

**Key Features:**
1. **Firejail Integration** - Full sandbox isolation using Firejail
2. **Command Validation** - Whitelist-based command security
3. **Resource Limits** - CPU, memory, disk, timeout controls
4. **Dry-Run Mode** - Preview commands without execution
5. **Rollback Capability** - Automatic rollback on failure
6. **Audit Logging** - Comprehensive command logging

**Firejail Command Structure (from existing code):**
```python
firejail_cmd = [
    firejail_path,
    "--quiet",           # Suppress firejail messages
    "--noprofile",       # Don't use default profile
    "--private",         # Private home directory
    "--private-tmp",     # Private /tmp
    f"--cpu={cpu_cores}",# CPU limit
    f"--rlimit-as={mem}",# Memory limit
    "--net=none",        # No network (configurable)
    "--noroot",          # No root access
    "--caps.drop=all",   # Drop all capabilities
    "--shell=none",      # No shell
    "--seccomp",         # Enable seccomp filtering
]
```

## Implementation Architecture

### New Module: `cortex/sandbox/sandbox_manager.py`

```
cortex/sandbox/
├── __init__.py
├── sandbox_executor.py      # Existing - command execution
├── sandbox_manager.py       # NEW - environment lifecycle management
├── sandbox_tester.py        # NEW - automated testing in sandbox
└── sandbox_example.py       # Existing - usage examples
```

### Core Classes Design

#### 1. SandboxEnvironment (Data Class)
```python
@dataclass
class SandboxEnvironment:
    """Represents a sandbox environment."""
    name: str
    created_at: datetime
    root_path: str              # e.g., ~/.cortex/sandboxes/{name}
    packages_installed: list[str]
    status: SandboxStatus       # created, active, testing, promoted, cleaned
    firejail_profile: str       # Custom firejail profile path
    network_enabled: bool       # Whether network access is allowed
    resource_limits: dict       # CPU, memory, disk limits
```

#### 2. SandboxManager (Main Manager)
```python
class SandboxManager:
    """Manages sandbox environment lifecycle."""

    def __init__(self, base_path: str = "~/.cortex/sandboxes"):
        self.base_path = os.path.expanduser(base_path)
        self.executor = SandboxExecutor()  # Reuse existing
        self.db_path = os.path.join(self.base_path, "sandboxes.db")

    # Environment Lifecycle
    def create(self, name: str, network: bool = False, **limits) -> SandboxEnvironment
    def destroy(self, name: str) -> bool
    def list_environments(self) -> list[SandboxEnvironment]
    def get_environment(self, name: str) -> SandboxEnvironment | None

    # Package Operations (using existing Firejail)
    def install_package(self, env_name: str, package: str, dry_run: bool = False) -> ExecutionResult
    def remove_package(self, env_name: str, package: str) -> ExecutionResult
    def list_packages(self, env_name: str) -> list[str]

    # Promotion
    def promote_to_system(self, env_name: str, dry_run: bool = False) -> PromotionResult

    # Status
    def get_status(self, env_name: str) -> dict
```

#### 3. SandboxTester (Test Runner)
```python
class SandboxTester:
    """Run automated tests in sandbox environments."""

    def __init__(self, manager: SandboxManager):
        self.manager = manager
        self.executor = manager.executor

    # Test Types
    def test_package_functional(self, env_name: str, package: str) -> TestResult
    def test_no_conflicts(self, env_name: str) -> TestResult
    def test_performance(self, env_name: str, package: str) -> TestResult
    def test_dependencies(self, env_name: str, package: str) -> TestResult

    # Full Test Suite
    def run_all_tests(self, env_name: str, package: str | None = None) -> list[TestResult]
```

## CLI Integration Plan

### New Commands Structure

```bash
cortex sandbox <action> [options]

Actions:
  create   <name>              Create a new sandbox environment
  list                         List all sandbox environments
  status   <name>              Show sandbox environment status
  install  <name> <package>    Install package in sandbox
  test     <name> [package]    Run tests in sandbox
  promote  <name>              Promote sandbox packages to main system
  cleanup  <name>              Remove sandbox environment
```

### CLI Implementation (in cli.py)

```python
# Add to main() argument parser
sandbox_parser = subparsers.add_parser("sandbox", help="Manage sandbox environments")
sandbox_subs = sandbox_parser.add_subparsers(dest="sandbox_action", help="Sandbox actions")

# sandbox create <name> [--network] [--cpu N] [--memory N] [--disk N]
sandbox_create = sandbox_subs.add_parser("create", help="Create sandbox environment")
sandbox_create.add_argument("name", help="Sandbox environment name")
sandbox_create.add_argument("--network", action="store_true", help="Enable network access")
sandbox_create.add_argument("--cpu", type=int, default=2, help="CPU cores limit")
sandbox_create.add_argument("--memory", type=int, default=2048, help="Memory limit (MB)")
sandbox_create.add_argument("--disk", type=int, default=1024, help="Disk limit (MB)")

# sandbox list
sandbox_subs.add_parser("list", help="List all sandbox environments")

# sandbox status <name>
sandbox_status = sandbox_subs.add_parser("status", help="Show sandbox status")
sandbox_status.add_argument("name", help="Sandbox environment name")

# sandbox install <name> <package> [--dry-run]
sandbox_install = sandbox_subs.add_parser("install", help="Install package in sandbox")
sandbox_install.add_argument("name", help="Sandbox environment name")
sandbox_install.add_argument("package", help="Package to install")
sandbox_install.add_argument("--dry-run", action="store_true", help="Preview only")

# sandbox test <name> [--package PKG]
sandbox_test = sandbox_subs.add_parser("test", help="Run tests in sandbox")
sandbox_test.add_argument("name", help="Sandbox environment name")
sandbox_test.add_argument("--package", help="Test specific package")

# sandbox promote <name> [--dry-run] [--force]
sandbox_promote = sandbox_subs.add_parser("promote", help="Promote to main system")
sandbox_promote.add_argument("name", help="Sandbox environment name")
sandbox_promote.add_argument("--dry-run", action="store_true", help="Preview only")
sandbox_promote.add_argument("--force", "-f", action="store_true", help="Skip confirmation")

# sandbox cleanup <name> [--force]
sandbox_cleanup = sandbox_subs.add_parser("cleanup", help="Remove sandbox")
sandbox_cleanup.add_argument("name", help="Sandbox environment name")
sandbox_cleanup.add_argument("--force", "-f", action="store_true", help="Skip confirmation")
```

## Firejail Integration Details

### Custom Sandbox Profile

Create per-sandbox Firejail profiles at `~/.cortex/sandboxes/{name}/firejail.profile`:

```ini
# Cortex Sandbox Profile for {name}
include /etc/firejail/default.profile

# Private directories (isolated)
private ${HOME}/.cortex/sandboxes/{name}/home
private-tmp
private-dev

# Whitelist for package installation
whitelist /var/cache/apt
whitelist /var/lib/apt
whitelist /var/lib/dpkg
read-only /etc/apt

# Resource limits
rlimit-as {memory_bytes}
rlimit-cpu {cpu_seconds}
rlimit-fsize {disk_bytes}

# Network (conditional)
{network_rule}  # "net none" or "net eth0"

# Security hardening
caps.drop all
seccomp
noroot
```

### Execution Flow

1. **Create Sandbox:**
   ```python
   def create(self, name: str, **options) -> SandboxEnvironment:
       # Create directory structure
       sandbox_root = os.path.join(self.base_path, name)
       os.makedirs(os.path.join(sandbox_root, "home"), exist_ok=True)
       os.makedirs(os.path.join(sandbox_root, "var"), exist_ok=True)

       # Generate Firejail profile
       profile = self._generate_profile(name, options)
       profile_path = os.path.join(sandbox_root, "firejail.profile")
       with open(profile_path, 'w') as f:
           f.write(profile)

       # Create environment record
       env = SandboxEnvironment(
           name=name,
           created_at=datetime.now(),
           root_path=sandbox_root,
           ...
       )
       self._save_environment(env)
       return env
   ```

2. **Install in Sandbox:**
   ```python
   def install_package(self, env_name: str, package: str, dry_run: bool = False):
       env = self.get_environment(env_name)

       # Build sandbox-specific firejail command
       cmd = self._build_sandbox_command(
           env,
           f"apt-get install -y {package}"
       )

       # Execute using existing SandboxExecutor
       result = self.executor.execute(cmd, dry_run=dry_run)

       if result.success and not dry_run:
           env.packages_installed.append(package)
           self._save_environment(env)

       return result

   def _build_sandbox_command(self, env: SandboxEnvironment, command: str) -> str:
       """Build command with sandbox-specific Firejail profile."""
       return (
           f"firejail --profile={env.firejail_profile} "
           f"--private={env.root_path}/home "
           f"{command}"
       )
   ```

3. **Test in Sandbox:**
   ```python
   def run_all_tests(self, env_name: str, package: str | None = None) -> list[TestResult]:
       results = []
       env = self.manager.get_environment(env_name)

       packages = [package] if package else env.packages_installed

       for pkg in packages:
           # Test 1: Package functional
           results.append(self.test_package_functional(env_name, pkg))

           # Test 2: No conflicts
           results.append(self.test_no_conflicts(env_name))

           # Test 3: Performance acceptable
           results.append(self.test_performance(env_name, pkg))

       return results

   def test_package_functional(self, env_name: str, package: str) -> TestResult:
       """Verify package runs without errors."""
       env = self.manager.get_environment(env_name)

       # Try to run package --version or --help
       test_commands = [
           f"{package} --version",
           f"{package} --help",
           f"dpkg -L {package} | head -20",  # List installed files
       ]

       for cmd in test_commands:
           result = self.manager.executor.execute(
               self.manager._build_sandbox_command(env, cmd),
               dry_run=False
           )
           if result.success:
               return TestResult(
                   test_name="Package Functional",
                   passed=True,
                   message=f"{package} is functional"
               )

       return TestResult(
           test_name="Package Functional",
           passed=False,
           message=f"{package} may not be functional"
       )
   ```

4. **Promote to System:**
   ```python
   def promote_to_system(self, env_name: str, dry_run: bool = False) -> PromotionResult:
       env = self.get_environment(env_name)

       if dry_run:
           return PromotionResult(
               success=True,
               packages=env.packages_installed,
               preview=True,
               message=f"Would install: {', '.join(env.packages_installed)}"
           )

       # Install packages on main system
       for package in env.packages_installed:
           # Uses main system apt, not sandboxed
           cmd = f"sudo apt-get install -y {package}"
           result = self.executor.execute(cmd, dry_run=False)
           if result.failed:
               return PromotionResult(
                   success=False,
                   packages=[package],
                   message=f"Failed to install {package}: {result.stderr}"
               )

       env.status = SandboxStatus.PROMOTED
       self._save_environment(env)

       return PromotionResult(
           success=True,
           packages=env.packages_installed,
           message="All packages promoted to main system"
       )
   ```

5. **Cleanup Sandbox:**
   ```python
   def destroy(self, name: str) -> bool:
       env = self.get_environment(name)
       if not env:
           return False

       # Remove sandbox directory tree
       shutil.rmtree(env.root_path, ignore_errors=True)

       # Remove from database
       self._delete_environment(name)

       return True
   ```

## Storage Structure

```
~/.cortex/
├── sandboxes/
│   ├── sandboxes.db              # SQLite database for environment metadata
│   ├── test-env/                 # Sandbox environment
│   │   ├── firejail.profile      # Custom Firejail profile
│   │   ├── home/                 # Private home directory
│   │   ├── var/                  # Private /var
│   │   └── logs/                 # Execution logs
│   └── dev-env/
│       └── ...
└── sandbox_audit.log             # Existing audit log
```

### Database Schema (SQLite)

```sql
CREATE TABLE sandboxes (
    name TEXT PRIMARY KEY,
    created_at TIMESTAMP,
    root_path TEXT,
    status TEXT,
    network_enabled BOOLEAN,
    cpu_limit INTEGER,
    memory_limit INTEGER,
    disk_limit INTEGER
);

CREATE TABLE sandbox_packages (
    sandbox_name TEXT,
    package_name TEXT,
    installed_at TIMESTAMP,
    version TEXT,
    FOREIGN KEY (sandbox_name) REFERENCES sandboxes(name)
);

CREATE TABLE sandbox_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sandbox_name TEXT,
    test_name TEXT,
    passed BOOLEAN,
    message TEXT,
    run_at TIMESTAMP,
    FOREIGN KEY (sandbox_name) REFERENCES sandboxes(name)
);
```

## Test Plan

### Unit Tests (>80% Coverage)

Create `tests/unit/test_sandbox_manager.py`:

```python
class TestSandboxManager(unittest.TestCase):
    """Test SandboxManager functionality."""

    def test_create_environment(self):
        """Test sandbox environment creation."""

    def test_create_environment_with_options(self):
        """Test sandbox creation with custom limits."""

    def test_list_environments(self):
        """Test listing all environments."""

    def test_get_environment(self):
        """Test retrieving specific environment."""

    def test_destroy_environment(self):
        """Test sandbox cleanup."""

    def test_install_package_success(self):
        """Test package installation in sandbox."""

    def test_install_package_dry_run(self):
        """Test dry-run installation."""

    def test_promote_packages(self):
        """Test promotion to main system."""

    def test_promote_dry_run(self):
        """Test promotion preview."""


class TestSandboxTester(unittest.TestCase):
    """Test SandboxTester functionality."""

    def test_functional_test_success(self):
        """Test functional testing passes."""

    def test_conflict_detection(self):
        """Test conflict detection works."""

    def test_performance_test(self):
        """Test performance validation."""

    def test_run_all_tests(self):
        """Test full test suite execution."""
```

### Integration Tests

Create `tests/integration/test_sandbox_integration.py`:

```python
class TestSandboxIntegration(unittest.TestCase):
    """End-to-end sandbox workflow tests."""

    def test_full_workflow(self):
        """Test create -> install -> test -> promote -> cleanup."""

    def test_firejail_isolation(self):
        """Test that sandbox is properly isolated."""
```

## Implementation Phases

### Phase 1: Core Infrastructure (Week 1)
- [ ] Create `SandboxEnvironment` dataclass
- [ ] Implement `SandboxManager` with create/list/destroy
- [ ] Add SQLite storage layer
- [ ] Write unit tests for core functionality

### Phase 2: Package Operations (Week 2)
- [ ] Implement `install_package` with Firejail isolation
- [ ] Implement `remove_package`
- [ ] Implement `list_packages`
- [ ] Add Firejail profile generation

### Phase 3: Testing Framework (Week 3)
- [ ] Implement `SandboxTester` class
- [ ] Add functional, conflict, performance tests
- [ ] Create test result reporting

### Phase 4: CLI Integration (Week 4)
- [ ] Add `sandbox` subcommand to CLI
- [ ] Implement all CLI actions
- [ ] Add Rich console output formatting
- [ ] Write CLI tests

### Phase 5: Documentation & Polish (Week 5)
- [ ] Write user documentation
- [ ] Add `--help` text for all commands
- [ ] Create usage examples
- [ ] Ensure >80% test coverage

## Example User Flow

```bash
# 1. Create sandbox environment
$ cortex sandbox create test-env
✓  Sandbox environment 'test-env' created
   Location: ~/.cortex/sandboxes/test-env
   Network: disabled (use --network to enable)
   Limits: 2 CPU cores, 2048MB memory, 1024MB disk

# 2. Install package in sandbox
$ cortex sandbox install test-env docker
🔍 Resolving dependencies for docker...
📦 Installing docker in sandbox 'test-env'...
✓  Docker installed in sandbox

# 3. Run automated tests
$ cortex sandbox test test-env
Running tests in sandbox 'test-env'...
   ✓  Package functional (docker --version works)
   ✓  No conflicts detected
   ✓  Performance acceptable (startup < 5s)

All tests passed!

# 4. Promote to main system
$ cortex sandbox promote test-env
The following packages will be installed on your main system:
  • docker

Promote to main system? [Y/n]: y
🚀 Installing docker on main system...
✓  Docker installed on main system

# 5. Cleanup sandbox
$ cortex sandbox cleanup test-env
Remove sandbox 'test-env' and all its data? [y/N]: y
✓  Sandbox 'test-env' removed
```

## Security Considerations

1. **Isolation**: All sandbox operations use Firejail with strict profiles
2. **No Root in Sandbox**: `--noroot` prevents privilege escalation
3. **Capability Dropping**: All capabilities dropped by default
4. **Seccomp Filtering**: System call filtering enabled
5. **Private Directories**: Sandbox has isolated home and tmp
6. **Network Control**: Network disabled by default
7. **Audit Logging**: All commands logged to audit trail

## Dependencies

- **Required**: Firejail (`apt-get install firejail`)
- **Python**: Standard library + existing cortex dependencies
- **Storage**: SQLite (built into Python)

## Conclusion

This implementation leverages the existing Firejail integration in `sandbox_executor.py` while adding:

1. **Environment Lifecycle Management** - Create, manage, destroy sandboxes
2. **Automated Testing** - Validate packages before promotion
3. **Safe Promotion** - Controlled installation to main system
4. **CLI Interface** - User-friendly commands matching the issue requirements

The design maintains backward compatibility with existing functionality while providing the full sandbox workflow requested.
