#!/usr/bin/env bash
set -e

# Make the repo dir be the current working directory
REPO_DIR=$(pwd)
echo "Repository directory: $REPO_DIR"
# Check if node and npm are installed
if ! command -v node &> /dev/null || ! command -v npm &> /dev/null; then
    echo "Node.js and npm are required but not installed. Please install them first."
    exit 1
fi

# Initialize npm
echo "Initializing npm..."
npm init -y
npm install --save-dev \
    @ai-hero/sandcastle \
    tsx

# Check if .sandcastle directory exists, if not create it
if [ ! -d "$REPO_DIR/.sandcastle" ]; then
    npx @ai-hero/sandcastle@latest init
fi
npm pkg set scripts.sandcastle="tsx .sandcastle/main.mts"

echo "Adding .env file to .sandcastle directory..."
cp ~/.env/.env "$REPO_DIR/.sandcastle/.env"

echo "Building sandcastle..."
npx @ai-hero/sandcastle docker build-image