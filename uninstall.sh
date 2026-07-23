#!/bin/bash
# Clean Uninstall Script for UT-Coder
# This script removes the docker containers, images, and the UT-Coder directory.

echo "====================================="
echo "   UT-Coder Clean Uninstall Script   "
echo "====================================="

echo "[1/3] Stopping and removing UT-Coder Docker containers..."
docker compose -f docker-compose.server.yml down -v --rmi all

echo "[2/3] Fixing permissions and removing UT-Coder directory..."
# Use docker to chown all files back to the current user (in case root created them)
docker run --rm -v $(pwd):/app ubuntu:22.04 chown -R $(id -u):$(id -g) /app
cd ..
rm -rf UT-coder


echo "[3/3] Uninstall complete!"
echo "The server is now clean."
