# Nexus Security Configuration

## Overview
This repository contains an AI agent (Nexus) that runs locally on your computer with specific security constraints.

## Security Restrictions

### 1. Internet Access via Commands
- **`run_command`**: Has NO internet access - commands run in isolated environment
- **`web_search`**: Can search the web using DuckDuckGo for information lookup only
- All other tools operate locally without network access

### 2. Remote Repository Access
- **Git Push Restrictions**: Cannot push to GitHub remotes due to:
  - No SSH keys or authentication tokens available
  - Security policy preventing unauthorized remote writes
  - Protection against accidental data leaks
  
### 3. File System Access
- Can read/write files in the working directory and subdirectories
- Can access home folder (~) for reading configuration
- Cannot write outside the working directory without explicit user request

### 4. User Authorization Required
- Any action that modifies remote repositories requires explicit user confirmation
- Security-sensitive operations are blocked by default
- Git credentials must be configured by the user before pushing

## Security Policies Implemented in Code

### Guardrails (`src/nexus/guardrails/policy.py`)
- Command allow/deny lists for dangerous operations
- Risk-based tool approval (NETWORK, EXEC, WRITE risks require user attention)
- Read-only mode blocks all write operations
- Auto mode stays within working directory by default

### Tool Risk Levels
- **Risk.NONE**: Safe operations (reading files, basic commands)
- **Risk.READ**: Reading from filesystem
- **Risk.WRITE**: Writing to filesystem (outside workspace requires approval)
- **Risk.NETWORK**: Network operations (search results, API calls)
- **Risk.EXEC**: Command execution (subject to allow-list)

## How to Enable Git Push Access

If you want Nexus to push commits:

1. Configure git credentials:
   ```bash
   git config --global user.name "Your Name"
   git config --global user.email "your@email.com"
   ```

2. Set up SSH key or use HTTPS with token:
   ```bash
   # For SSH
   ssh-keygen -t ed25519 -C "your@email.com"
   cat ~/.ssh/id_ed25519.pub | xclip  # macOS clipboard
   
   # Add to GitHub and then push
   git remote add origin https://github.com/omerrz1/NEXUS.git
   git push origin main
   ```

3. Or configure credential helper for HTTPS:
   ```bash
   git config --global credential.helper store
   ```

## Security Best Practices

- Never commit sensitive keys or tokens to the repository
- Review all changes before committing
- Keep guardrails enabled in production environments
- Regularly update policy rules as new tools are added
- Monitor for unauthorized access attempts

## Incident Response

If you notice suspicious activity:
1. Revoke any compromised credentials immediately
2. Review recent commits and revert if necessary
3. Update security policies in `src/nexus/guardrails/policy.py`
4. Consider enabling additional restrictions

---
*This security configuration was last updated by the user.*
