# CLAUDE.md - AI Agent Guidelines

This document provides essential guidelines for AI agents working on this codebase.

## Critical Context

**This code controls heating for real homes.** Mistakes can result in:
- Pipes freezing and bursting (costly property damage)
- Excessive energy bills
- Uncomfortable living conditions
- Hardware damage to valves and boilers

**Quality and correctness are paramount.** When in doubt, ask questions rather than make assumptions.

## Environment Setup

**ALWAYS run before any code quality checks:**

```bash
uv sync --all-extras
```

This installs all dependencies including test and dev extras (pytest, ruff, ty).

The `--all-extras` flag is equivalent to `--extra test --extra dev` and ensures all tools are available.

## Pre-Commit Checklist

**BEFORE committing any changes, run ALL of these checks in order:**

```bash
# 1. Run tests first - ensures code works correctly
uv run pytest

# 2. Format code with ruff (auto-fixes formatting issues)
uv run ruff format .

# 3. Lint with ruff (auto-fixes what it can)
uv run ruff check . --fix

# 4. Type check with ty
uv run ty check
```

**All checks must pass before committing.** CI will reject PRs that fail any of these.

## Project Structure

```
custom_components/ufh_controller/
├── __init__.py          # Entry point, async_setup_entry
├── coordinator.py       # DataUpdateCoordinator (main control loop)
├── config_flow.py       # UI configuration flows
├── const.py             # Constants, defaults, enums
├── core/
│   ├── controller.py    # Control logic orchestration
│   ├── zone.py          # Zone state and decision logic
│   ├── pid.py           # PID controller implementation
│   └── history.py       # Recorder query helpers
├── climate.py           # Climate entity platform
├── sensor.py            # Sensor entities (duty cycle, PID values)
├── binary_sensor.py     # Binary sensors (blocked, heat request)
├── select.py            # Mode selector entity
└── switch.py            # Switch entities (flush enabled)

tests/                   # Test suite (see Test Organization below)
│   ├── unit/            # Pure logic tests, no HA dependencies
│   ├── integration/     # Entity platform tests with mocked HA
│   ├── scenarios/       # End-to-end workflows and resilience
│   └── config/          # Config flows and setup lifecycle
docs/specification.md    # Technical specification document
```

## Specification Synchronization

**The `docs/specification.md` file is the source of truth for design decisions.**

When making changes:
1. Check if your changes align with the specification
2. If changes conflict with the specification, update BOTH the code AND specification
3. Never leave the specification out of sync with the implementation
4. Document any new features, entities, or configuration options in the specification

## Testing Requirements

### Test Coverage
- **Minimum 80% line coverage** (enforced in pyproject.toml)
- **Goal: 90%+ for core/ modules** (critical control logic)

### Bug Fixes: Reproduce First
When fixing bugs:
1. **Write a failing test case first** that reproduces the bug
2. Verify the test fails as expected
3. Implement the fix
4. Verify the test now passes
5. Add any additional edge case tests

This ensures bugs don't regress and documents the expected behavior.

### New Features: Test Thoroughly
- Write tests for all new functionality
- Cover edge cases (null values, boundary conditions, error states)
- Test integration with Home Assistant entities where applicable

### Test Fixtures
Common fixtures are in `tests/conftest.py`:
- `mock_config_entry` - Config entry with one zone
- `mock_config_entry_no_zones` - Config entry without zones
- `mock_recorder` - Mocked Home Assistant recorder

### Test Organization

Tests are organized into four directories based on their scope and dependencies:

**`tests/unit/`** - Pure logic tests
- Testing a single class/function in isolation
- No Home Assistant dependencies (no `hass` fixture)
- Examples: PID controller math, observation window calculations

**`tests/integration/`** - Entity platform tests
- Testing entity platforms (climate, sensor, binary_sensor, etc.)
- Testing component interaction with mocked Home Assistant state
- Requires `hass` fixture and mock entities
- Examples: climate entity behavior, controller orchestration, zone evaluation

**`tests/scenarios/`** - End-to-end workflow tests
- Testing realistic user workflows from start to finish
- Testing resilience (failures, recovery, state persistence)
- Multi-step operations over time (coordinator updates)
- Examples: state persistence across restarts, database failure recovery

**`tests/config/`** - Configuration and setup tests
- Testing config flows (UI configuration)
- Testing setup/unload lifecycle
- Testing conditional entity creation based on config
- Examples: config flow validation, entry setup/unload

## Code Quality Standards

### Ruff Configuration
- Line length: 88 characters
- Target: Python 3.13+
- Select: ALL rules (with specific ignores, see pyproject.toml)
- Tests have relaxed rules for asserts, magic values, etc.

### Type Annotations
- Use type hints for all function signatures
- Use TypedDict for structured dictionaries (see const.py)
- Run `uv run ty check` to verify

### Constants
- Extract magic numbers to `const.py`
- Use typed defaults (TimingDefaults, PIDDefaults, SetpointDefaults)
- Document units in comments (seconds, percentages, ratios)

## Git Commit Practices

### Good Commit History
- **Each meaningful change deserves its own commit**
- Write clear, descriptive commit messages
- Use conventional format: `Fix X`, `Add Y`, `Update Z`

### When to Amend
Only amend commits for:
- Re-running linter/formatter (formatting fixes)
- Fixing typos in the same logical change
- Never amend commits that are already pushed

### When NOT to Amend
- Meaningful code changes should always be new commits
- Bug fixes that change behavior
- New features or refactors

## Common Pitfalls to Avoid

### 1. Forgetting `uv sync`
```bash
# WRONG - tools not installed
uv run pytest  # Error: pytest not found

# RIGHT
uv sync --all-extras
uv run pytest
```

### 2. Committing Without Full Check Cycle
```bash
# WRONG - only ran tests
uv run pytest
git commit

# RIGHT - full verification
uv run pytest && uv run ruff format . && uv run ruff check . --fix && uv run ty check
git commit
```

### 3. Not Updating Specification
```python
# WRONG - Added new entity without documenting
# (creates silent drift between docs and code)

# RIGHT - Update docs/specification.md with new entity details
```

### 4. Fixing Bugs Without Tests
```python
# WRONG - Just fix the code
def calculate_duty_cycle(...):
    return fixed_value  # "trust me it works now"

# RIGHT - Write failing test first
def test_duty_cycle_edge_case():
    # This test should fail before the fix
    assert calculate_duty_cycle(edge_case) == expected
```

## CI Workflows

The CI runs three workflow files on PRs:

1. **checks.yml** - Unit tests with pytest
2. **lint.yml** - Ruff check, Ruff format, ty type check
3. **validate.yml** - Hassfest and HACS validation

All must pass for PR approval.

## Quick Reference Commands

```bash
# Setup environment
uv sync --all-extras

# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=custom_components/ufh_controller

# Format code
uv run ruff format .

# Lint and auto-fix
uv run ruff check . --fix

# Type check
uv run ty check

# Full pre-commit check
uv run pytest && uv run ruff format . && uv run ruff check . --fix && uv run ty check

# Bump version (updates pyproject.toml and manifest.json)
uv run bump-my-version bump patch  # 0.1.3 → 0.1.4
uv run bump-my-version bump minor  # 0.1.3 → 0.2.0
uv run bump-my-version bump major  # 0.1.3 → 1.0.0
```

## Domain Knowledge

### PID Control
- Proportional-Integral-Derivative controller for temperature regulation
- Output is duty cycle (0-100%) representing heating demand
- Integral term has anti-windup protection

### Observation Period
- 2-hour windows aligned to even hours (00:00, 02:00, 04:00...)
- Zones get quota based on duty cycle average
- Prevents rapid valve cycling

### Safety Features
- Window/door detection blocks heating (prevents energy waste)
- Minimum run time prevents valve wear
- DHW (hot water) priority for system coordination

### Home Assistant Integration
- Uses ConfigEntry with subentries for zones
- DataUpdateCoordinator for state management
- Recorder queries for historical state averages
