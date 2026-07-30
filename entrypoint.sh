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

echo "🔴 Retrieve qwen2.5:3b model..."
ollama pull qwen2.5:3b
echo "🟢 Done!"

# Wait for Ollama process to finish.
wait $pid
