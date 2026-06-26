# Source - https://stackoverflow.com/a/78501628
# Posted by datawookie
# Retrieved 2026-05-20, License - CC BY-SA 4.0

#!/bin/bash

# Start Ollama in the background.
/bin/ollama serve &
# Record Process ID.
pid=$!

# Pause for Ollama to start.
sleep 20

echo "🔴 Retrieve gemma4:e2b model..."
ollama pull gemma4:e2b 
echo "🟢 Done!"

# Wait for Ollama process to finish.
wait $pid
