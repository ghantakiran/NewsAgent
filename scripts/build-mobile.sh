#!/bin/bash
set -e

echo "=== NewsAgent Mobile Build Helper ==="
echo ""

cd "$(dirname "$0")/../mobile"

# Check required tools
command -v npx >/dev/null 2>&1 || { echo "Error: npx required (install Node.js)"; exit 1; }
command -v eas >/dev/null 2>&1 || {
    echo "EAS CLI not found. Installing..."
    npm install -g eas-cli
}

# Check login
echo "Checking EAS login..."
eas whoami 2>/dev/null || {
    echo "Not logged in to EAS. Please run: eas login"
    exit 1
}

# Ensure dependencies installed
echo "Installing dependencies..."
npm install

# TypeScript check
echo "Running TypeScript check..."
npx tsc --noEmit
echo "TypeScript: OK"

PLATFORM="${1:-all}"
PROFILE="${2:-production}"

echo ""
echo "Building for platform: $PLATFORM, profile: $PROFILE"
echo ""

if [ "$PLATFORM" = "all" ]; then
    echo "Building iOS..."
    eas build --platform ios --profile "$PROFILE" --non-interactive
    echo ""
    echo "Building Android..."
    eas build --platform android --profile "$PROFILE" --non-interactive
else
    eas build --platform "$PLATFORM" --profile "$PROFILE" --non-interactive
fi

echo ""
echo "Build complete! Check status at: https://expo.dev"
echo ""
echo "To submit to stores:"
echo "  eas submit --platform ios --profile $PROFILE"
echo "  eas submit --platform android --profile $PROFILE"
