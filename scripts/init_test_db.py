#!/usr/bin/env python3
# GNU Affero General Public License v3.0 only
# Copyright (c) 2025 sliptonic
# SPDX-License-Identifier: AGPL-3.0-only
"""
Initialize test database with test users via API.

This script creates test users via the API:
1. Registers the first admin user via API (on fresh database)
2. Creates additional test users via API (requires admin auth)

Test users created:
- admin@test.com (admin)
- user@test.com (normal user)
- manufacturer@test.com (manufacturer)

Prerequisites:
- Server must be running at the specified base URL
- For a fresh database: delete the database file and restart server first
- Server will automatically initialize schema on startup

Usage:
    # For fresh database:
    rm loobric.db && <restart server>
    python init_test_db.py [--base-url BASE_URL]
    
Examples:
    python init_test_db.py                                    # Uses http://127.0.0.1:8000
    python init_test_db.py --base-url http://localhost:8000   # Custom API URL
"""

import sys
import argparse
import subprocess
from pathlib import Path


def run_cli_command(args, input_text=None):
    """Run the loobric CLI command (requires the loobric-cli package; e.g.
    `pip install -e ../loobric-cli`).

    Args:
        args: List of command arguments
        input_text: Optional stdin input for the command

    Returns:
        subprocess.CompletedProcess: Result of the command
    """
    cmd = ["python3", "-m", "loobric.cli.main"] + args
    
    result = subprocess.run(
        cmd,
        input=input_text,
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        print(f"Error running command: {' '.join(args)}")
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
        sys.exit(1)
    
    return result


def init_test_database(base_url: str = "http://127.0.0.1:8000"):
    """Initialize test database with test users via API.
    
    Args:
        base_url: Base URL of the API server
    """
    
    print("=" * 60)
    print("Initializing Test Database")
    print("=" * 60)
    print(f"API URL: {base_url}")
    print("\nNote: Server must be running for this script to work.")
    print("      For fresh database: delete loobric.db and restart server first.")
    
    print("\n1. Registering admin user via API...")
    # Register first user (becomes admin automatically)
    run_cli_command(
        ["--base-url", base_url, "register", "admin@test.com", "--password", "admin"]
    )
    print("   ✓ Admin user registered")
    
    print("\n4. Logging in as admin...")
    run_cli_command(
        ["--base-url", base_url, "login", "admin@test.com", "--password", "admin"]
    )
    print("   ✓ Logged in")
    
    print("\n5. Creating additional users via API...")
    # Create normal user
    run_cli_command(
        ["--base-url", base_url, "register", "user@test.com", "--password", "user"]
    )
    print("   ✓ Created user@test.com")
    
    # Create manufacturer user
    run_cli_command(
        ["--base-url", base_url, "register", "manufacturer@test.com", "--password", "manufacturer"]
    )
    print("   ✓ Created manufacturer@test.com")
    
    print("\n6. Creating API keys for each user...")
    
    # Admin user already logged in, create their key
    result = run_cli_command(
        ["--base-url", base_url, "create-key", "Admin API Key", 
         "--scopes", "read write:items write:presets write:assemblies"]
    )
    admin_api_key = result.stdout.strip()
    print("   ✓ Created admin API key")
    
    # Logout and login as normal user
    run_cli_command(["--base-url", base_url, "logout"])
    run_cli_command(
        ["--base-url", base_url, "login", "user@test.com", "--password", "user"]
    )
    result = run_cli_command(
        ["--base-url", base_url, "create-key", "User API Key", 
         "--scopes", "read write:items"]
    )
    user_api_key = result.stdout.strip()
    print("   ✓ Created user API key")
    
    # Logout and login as manufacturer user
    run_cli_command(["--base-url", base_url, "logout"])
    run_cli_command(
        ["--base-url", base_url, "login", "manufacturer@test.com", "--password", "manufacturer"]
    )
    result = run_cli_command(
        ["--base-url", base_url, "create-key", "Manufacturer API Key", 
         "--scopes", "read write:items write:presets"]
    )
    manufacturer_api_key = result.stdout.strip()
    print("   ✓ Created manufacturer API key")
    
    print("\n" + "=" * 60)
    print("✓ Test Database Initialized Successfully!")
    print("=" * 60)
    
    print(f"\n1. Admin User:")
    print(f"  Email:    admin@test.com")
    print(f"  Password: admin")
    print(f"  API Key:  {admin_api_key}")
    
    print(f"\n2. Normal User:")
    print(f"  Email:    user@test.com")
    print(f"  Password: user")
    print(f"  API Key:  {user_api_key}")
    
    print(f"\n3. Manufacturer User:")
    print(f"  Email:    manufacturer@test.com")
    print(f"  Password: manufacturer")
    print(f"  API Key:  {manufacturer_api_key}")
    
    print(f"\nUsage:")
    print(f"  # Use API key directly")
    print(f"  export LOOBRIC_API_KEY={admin_api_key}")
    print()
    print(f"  # Or login with CLI")
    print(f"  loobric login admin@test.com")
    print()
    print(f"  # Create more API keys")
    print(f"  loobric create-key \"My Key\" --scopes \"read write:items\"")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Initialize test database with sample users via API"
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the API server (default: http://127.0.0.1:8000)"
    )
    
    args = parser.parse_args()
    init_test_database(args.base_url)
