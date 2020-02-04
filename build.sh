#!/bin/sh

# This script builds the `vertex-oven-<version>.zip` addon file.
# Usage: ./build.sh

ADDON_DIR=$(basename `pwd`)

# Produce the version string (for example, "0.1.4" without the quotes.)
VERSION=$(cat __init__.py | sed -n 's/.*\"version\"://p' | tr -d ' (' | sed -e "s/),//" | tr ',' '.')

echo "Packing Vertex Oven, version" $VERSION

echo

ADDON_FILENAME=vertex-oven-$VERSION.zip

echo "Compressing addon files to" $ZIP_FILENAME "..."

cd ..

zip $ADDON_FILENAME $ADDON_DIR/__init__.py
zip $ADDON_FILENAME $ADDON_DIR/README.md
zip $ADDON_FILENAME $ADDON_DIR/LICENSE

mv $ADDON_FILENAME $ADDON_DIR/builds/$ADDON_FILENAME

cd -

echo

echo "Complete; see directory ./builds/"

ls -ltrh builds/$ADDON_FILENAME
