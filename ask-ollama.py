import os
import requests
import json
import sys

# Configuration
KNOWLEDGE_DIR = os.path.expanduser("~/ollama_knowledge")
OLLAMA_API = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b"

def get_context():
    """Reads all compatible files from the knowledge directory to build a context string."""
    context = ""
    if not os.path.exists(KNOWLEDGE_DIR):
        return context
    
    files_read = 0
    for filename in os.listdir(KNOWLEDGE_DIR):
        # Filter for text-based files
        if filename.endswith((".txt", ".md", ".py", ".js", ".html", ".css", ".json")):
            filepath = os.path.join(KNOWLEDGE_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                    context += f"\n--- DOCUMENT: {filename} ---\n{content}\n"
                    files_read += 1
            except Exception as e:
                print(f"Warning: Could not read {filename}: {e}", file=sys.stderr)
    
    if files_read > 0:
        print(f"(System: Loaded {files_read} files from knowledge base)", file=sys.stderr)
    return context

def ask(query):
    """Sends a query to Ollama with the aggregated context."""
    context = get_context()
    
    # Constructing a prompt that explicitly uses the provided context
    prompt = f"""You are a personal assistant. You have access to a folder of 'personal knowledge' documents. 
Your goal is to answer the user's question using these documents whenever possible.
If the answer is found in the documents, emphasize that. 
If not, use your general knowledge but clarify that the information wasn't in your personal files.

=== START KNOWLEDGE BASE ===
{context}
=== END KNOWLEDGE BASE ===

USER QUESTION: {query}
"""
    
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": True
    }
    
    try:
        response = requests.post(OLLAMA_API, json=payload, stream=True)
        response.raise_for_status()
        
        print("\nOllama: ", end="", flush=True)
        for line in response.iter_lines():
            if line:
                chunk = json.loads(line.decode("utf-8"))
                if "response" in chunk:
                    print(chunk["response"], end="", flush=True)
                if chunk.get("done"):
                    print("\n")
    except requests.exceptions.ConnectionError:
        print("\nError: Could not connect to Ollama. Is the service running?", file=sys.stderr)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        query_text = " ".join(sys.argv[1:])
        ask(query_text)
    else:
        # Interactive mode helper
        print("--- Personal LLM Context Helper ---")
        print("Usage: python3 ask-ollama.py 'your question'")
        print(f"Files are loaded from: {KNOWLEDGE_DIR}")
        print("----------------------------------")
        while True:
            try:
                user_input = input("\nAsk (or 'exit'): ")
                if user_input.lower() in ["exit", "quit", "q"]:
                    break
                if user_input.strip():
                    ask(user_input)
            except KeyboardInterrupt:
                break
