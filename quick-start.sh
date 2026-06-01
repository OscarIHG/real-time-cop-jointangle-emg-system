#!/bin/bash
# =============================================================================
# Quick Start Script for Real-Time CoP-JointAngle-EMG System
# Automated setup and deployment with Docker
# =============================================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "====================================================================="
echo "  Real-Time CoP-JointAngle-EMG System - Quick Start"
echo "====================================================================="
echo -e "${NC}"

# Check if running on Raspberry Pi
if [ -f /proc/device-tree/model ]; then
    MODEL=$(cat /proc/device-tree/model)
    echo -e "${GREEN}✓ Detected: $MODEL${NC}"
else
    echo -e "${YELLOW}⚠ Warning: Not running on Raspberry Pi${NC}"
fi

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check Docker
echo -e "\n${BLUE}[1/5] Checking Docker...${NC}"
if command_exists docker; then
    echo -e "${GREEN}✓ Docker is installed${NC}"
    docker --version
else
    echo -e "${RED}✗ Docker is not installed${NC}"
    echo -e "${YELLOW}Installing Docker...${NC}"
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo -e "${GREEN}✓ Docker installed. Please log out and log back in.${NC}"
    exit 0
fi

# Check Docker Compose
echo -e "\n${BLUE}[2/5] Checking Docker Compose...${NC}"
if command_exists docker-compose || docker compose version >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Docker Compose is available${NC}"
else
    echo -e "${RED}✗ Docker Compose is not installed${NC}"
    echo -e "${YELLOW}Installing Docker Compose...${NC}"
    sudo apt-get update
    sudo apt-get install -y docker-compose
    echo -e "${GREEN}✓ Docker Compose installed${NC}"
fi

# Setup X11 for GUI
echo -e "\n${BLUE}[3/5] Setting up X11 access...${NC}"
xhost +local:docker 2>/dev/null || echo -e "${YELLOW}⚠ Could not configure X11 (GUI may not work)${NC}"

# Create data directory
echo -e "\n${BLUE}[4/5] Creating data directory...${NC}"
mkdir -p data
echo -e "${GREEN}✓ Data directory ready${NC}"

# Build and start
echo -e "\n${BLUE}[5/5] Building and starting container...${NC}"
echo -e "${YELLOW}This may take 10-15 minutes on first run...${NC}"

if [ -f docker-compose.yml ]; then
    docker-compose up -d --build
    echo -e "\n${GREEN}✓ Container started successfully!${NC}"
else
    echo -e "${RED}✗ docker-compose.yml not found${NC}"
    exit 1
fi

# Show logs
echo -e "\n${BLUE}=====================================================================${NC}"
echo -e "${GREEN}✓ Setup complete!${NC}"
echo -e "\n${BLUE}Useful commands:${NC}"
echo -e "  ${YELLOW}View logs:${NC}        docker-compose logs -f"
echo -e "  ${YELLOW}Stop system:${NC}      docker-compose down"
echo -e "  ${YELLOW}Restart:${NC}          docker-compose restart"
echo -e "  ${YELLOW}Access shell:${NC}     docker-compose exec cop-emg-system bash"
echo -e "  ${YELLOW}Update image:${NC}     docker-compose up -d --build"
echo -e "\n${BLUE}GUI Access:${NC}"
echo -e "  The GUI should appear automatically."
echo -e "  If not, check logs with: docker-compose logs -f"
echo -e "\n${BLUE}Data Location:${NC}"
echo -e "  Recorded data will be saved in: ${PWD}/data/"
echo -e "\n${BLUE}=====================================================================${NC}"

# Show container status
echo -e "\n${BLUE}Container Status:${NC}"
docker-compose ps

echo -e "\n${GREEN}🚀 System is ready! Check logs above for any errors.${NC}"
