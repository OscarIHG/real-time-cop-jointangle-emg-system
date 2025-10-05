#!/bin/bash

# Optimized Acquisition System Installer
# Installs the multiprocessing optimization for 20-30 FPS performance

echo "🚀 Installing Optimized Acquisition System..."
echo "Expected performance: 20-30 FPS (vs 1.5-2 FPS original)"
echo ""

# Kill any existing processes
echo "Stopping existing processes..."
pkill -f "python.*app_gui"
sleep 2

# Check if we're in the right branch
CURRENT_BRANCH=$(git branch --show-current)
echo "Current branch: $CURRENT_BRANCH"

if [ "$CURRENT_BRANCH" != "feature/multiprocessing-optimization" ]; then
    echo "Switching to optimization branch..."
    git fetch origin
    git checkout feature/multiprocessing-optimization
fi

# Verify files exist
if [ ! -f "acquisition_systems/app_gui_optimized.py" ]; then
    echo "❌ ERROR: Optimized GUI file not found!"
    echo "Make sure you're in the correct repository directory."
    exit 1
fi

if [ ! -d "acquisition_systems/workers_mp" ]; then
    echo "❌ ERROR: Optimized workers directory not found!"
    exit 1
fi

echo "✅ All optimization files found"

# Check system requirements
echo ""
echo "=== System Requirements Check ==="
echo "CPU cores: $(nproc)"
echo "Python version: $(python3 --version)"
echo "Memory: $(free -h | grep Mem | awk '{print $2}')"

if [ $(nproc) -lt 4 ]; then
    echo "⚠️  WARNING: Less than 4 CPU cores. Performance may be limited."
else
    echo "✅ Good: $(nproc) cores available for multiprocessing"
fi

# Test import of optimized modules
echo ""
echo "Testing optimized modules..."
python3 -c "from acquisition_systems.workers_mp.runtime_optimized import start_workers_optimized; print('✅ Multiprocessing runtime OK')" 2>/dev/null || echo "❌ Multiprocessing runtime import failed"
python3 -c "from acquisition_systems.app_gui_optimized import OptimizedApp; print('✅ Optimized GUI OK')" 2>/dev/null || echo "❌ Optimized GUI import failed"

echo ""
echo "=== Installation Complete! ==="
echo ""
echo "To run the optimized version:"
echo "  python3 acquisition_systems/app_gui_optimized.py"
echo ""
echo "To verify multiprocessing is working:"
echo "  # In another terminal while GUI is running:"
echo "  ps aux | grep python"
echo "  # You should see 4-5 separate python processes"
echo ""
echo "Expected performance improvement:"
echo "  • GUI FPS: 1.5-2 → 20-30 FPS"
echo "  • CoP processing: Very slow → 20-25 FPS"
echo "  • CPU utilization: Single core → Multi-core"
echo ""
