#!/bin/bash

# Change to the Freqtrade directory
cd /home/danson/Servers/Freqtrade/ || exit 1

# Activate virtual environment
source ./.venv/bin/activate

# Start the Freqtrade trading process in an infinite loop
while true; do
    freqtrade trade --config user_data/config-7.json

    echo "Freqtrade stopped at $(date). Restarting in 5 seconds..."
    sleep 5
done