#!/bin/bash
# Auto-push script for hermes-creative-works
# Usage: ./auto_push.sh "commit message"

cd /root/hermes-novel-project

# Check if there are changes to commit
if ! git diff --quiet --cached; then
    echo "There are staged changes to commit"
elif ! git diff --quiet; then
    echo "There are unstaged changes. Staging all..."
    git add --all
else
    echo "No changes to commit"
    exit 0
fi

# Commit with provided message
if [ -z "$1" ]; then
    COMMIT_MSG="Auto-update novel project - $(date '+%Y-%m-%d %H:%M')"
else
    COMMIT_MSG="$1"
fi

git commit -m "$COMMIT_MSG"

# Push to GitHub
if git push origin main; then
    echo "✓ Successfully pushed to GitHub"
else
    echo "✗ Failed to push to GitHub"
    exit 1
fi