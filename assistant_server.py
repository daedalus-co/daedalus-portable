import http.server
import socketserver
import json
import os
import urllib.request
import urllib.error
import urllib.parse
import sys
import re
import time

# Configuration
PORT = 8012
KNOWLEDGE_DIR = os.path.expanduser("~/ollama_knowledge")
OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
MODEL = "daedalus-llama"

def search_web(query):
    """Simple DuckDuckGo scraper for zero-key search."""
    print(f"[Tool] Searching web for: {query}")
    try:
        url = f"https://duckduckgo.com/lite/?q={urllib.parse.quote(query)}"
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8', errors='ignore')
            # Fallback regex matches for links and snippets in DDG Lite
            # Titles are in <a class="result-link">
            # Snippets are in <td class="result-snippet">
            results = []
            links = re.findall(r'href="([^"]+)"[^>]*class="result-link"[^>]*>([^<]+)</a>', html)
            snippets = re.findall(r'<td class="result-snippet">([^<]+)</td>', html)
            
            if not links: # Attempt second regex style
                links = re.findall(r'href="([^"]+)"[^>]*>([^<]+)</a>', html)
                # Filter out clear nav links
                links = [l for l in links if "duckduckgo.com" not in l[0] and len(l[1]) > 5]

            for i in range(min(5, len(links))):
                title = links[i][1].strip()
                link = links[i][0]
                snippet = snippets[i].strip() if i < len(snippets) else "No snippet"
                results.append(f"[{i+1}] {title} ({link}): {snippet}")
            
            return "\\n".join(results) if results else "Search returned no matches. Try a different query."
    except Exception as e:
        return f"Search error: {str(e)}"

def modify_file(filename, content):
    """Writes content to a file within the knowledge base directory."""
    print(f"[Tool] Modifying file: {filename}")
    try:
        # Sanitize filename and prevent directory traversal
        filename = os.path.basename(filename)
        filepath = os.path.abspath(os.path.join(KNOWLEDGE_DIR, filename))
        if not filepath.startswith(os.path.abspath(KNOWLEDGE_DIR)):
            return "Error: Permission denied. Access restricted to knowledge base folder."
        
        os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully updated '{filename}' in the knowledge base."
    except Exception as e:
        return f"File modification failed: {str(e)}"

class AgenticHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200); self.send_header('Content-type', 'text/html'); self.end_headers()
            self.wfile.write(HTML_CONTENT.encode('utf-8'))
        elif self.path == '/api/files':
            self.handle_list_files()
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/chat':
            self.handle_chat()
        elif self.path == '/api/read-file':
            self.handle_read_file()
        else:
            self.send_error(404)

    def handle_list_files(self):
        files = sorted([f for f in os.listdir(KNOWLEDGE_DIR) if f.endswith(('.txt', '.md', '.py', '.js', '.json'))]) if os.path.exists(KNOWLEDGE_DIR) else []
        self.send_json({"files": files})

    def handle_read_file(self):
        length = int(self.headers['Content-Length']); data = json.loads(self.rfile.read(length))
        path = os.path.join(KNOWLEDGE_DIR, os.path.basename(data['filename']))
        try:
            with open(path, 'r', encoding='utf-8') as f: content = f.read()
            self.send_json({"content": content})
        except: self.send_error(404)

    def handle_chat(self):
        length = int(self.headers['Content-Length']); payload = json.loads(self.rfile.read(length))
        print(f"[Chat] New request: {payload.get('messages', [])[-1].get('content')[:50]}...")
        
        tools = [{
            "type": "function",
            "function": {
                "name": "search_web", "description": "Search the internet for real-time information",
                "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
            }
        }, {
            "type": "function",
            "function": {
                "name": "modify_file", "description": "Write or update a file in the knowledge base",
                "parameters": {"type": "object", "properties": {"filename": {"type": "string"}, "content": {"type": "string"}}, "required": ["filename", "content"]}
            }
        }]

        messages = payload.get('messages', [])
        
        try:
            self.send_response(200); self.send_header('Content-Type', 'application/x-ndjson'); self.end_headers()
            
            for turn in range(3): # Max turns
                print(f"[Agent] Turn {turn+1}...")
                chat_data = {"model": MODEL, "messages": messages, "stream": True, "tools": tools}
                req = urllib.request.Request(OLLAMA_CHAT_URL, data=json.dumps(chat_data).encode('utf-8'), method='POST')
                req.add_header('Content-Type', 'application/json')
                
                with urllib.request.urlopen(req) as resp:
                    current_msg = {"role": "assistant", "content": "", "tool_calls": []}
                    
                    for line in resp:
                        if not line: continue
                        chunk = json.loads(line.decode('utf-8'))
                        if 'message' in chunk:
                            m = chunk['message']
                            if 'content' in m and m['content']:
                                current_msg['content'] += m['content']
                                self.wfile.write(line); self.wfile.flush()
                            if 'tool_calls' in m:
                                # Explicitly ensure we are dealing with a list
                                if isinstance(m['tool_calls'], list):
                                    current_msg['tool_calls'].extend(m['tool_calls'])
                    
                    messages.append(current_msg)
                    
                    tc_list = current_msg.get('tool_calls', [])
                    if not tc_list: break 
                    
                    for tc in tc_list:
                        # Ensure tc is a dict before indexing
                        if not isinstance(tc, dict): continue
                        func = tc.get('function', {})
                        fname = func.get('name')
                        fargs = func.get('arguments', {})
                        print(f"[Agent] Calling {fname} with {fargs}")
                        
                        # Notify client
                        status = {"message": {"role": "system", "content": f"Executing {fname}..."}}
                        self.wfile.write((json.dumps(status) + "\\n").encode('utf-8')); self.wfile.flush()
                        
                        res = ""
                        if fname == "search_web": res = search_web(fargs.get('query', ''))
                        elif fname == "modify_file": res = modify_file(fargs.get('filename',''), fargs.get('content',''))
                        
                        messages.append({"role": "tool", "content": res})
                        print(f"[Agent] Tool result: {res[:50]}...")
            
            print("[Agent] Turn complete.")
        except Exception as e:
            print(f"Error: {e}")
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))

    def send_json(self, data):
        self.send_response(200); self.send_header('Content-type', 'application/json'); self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Daedalus Agent</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;600&family=Inter:wght@400;600&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <style>
        :root { --accent: #6366f1; --bg: #0a0c10; --glass: rgba(255,255,255,0.05); }
        body { margin: 0; font-family: 'Inter', sans-serif; background: var(--bg); color: #e2e8f0; height: 100vh; display: flex; overflow: hidden; }
        .app { display: flex; width: 100%; height: 100%; }
        .panel { width: 300px; background: var(--glass); border-right: 1px solid rgba(255,255,255,0.1); padding: 20px; transition: 0.3s; }
        .collapsed { width: 0; padding: 0; border: none; overflow: hidden; }
        .chat-view { flex-grow: 1; display:flex; flex-direction:column; align-items:center; background: radial-gradient(circle, #111827, #0a0c10); }
        .chat-inner { width: 100%; max-width: 800px; display: flex; flex-direction: column; height: 100%; padding: 40px 20px; }
        .messages { flex-grow: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 20px; scroll-behavior: smooth; }
        .msg { padding: 15px 20px; border-radius: 15px; max-width: 85%; line-height: 1.6; }
        .user { align-self: flex-end; background: var(--accent); }
        .ai { align-self: flex-start; background: var(--glass); border: 1px solid rgba(255,255,255,0.1); }
        .sys { align-self: center; font-size: 0.8rem; opacity: 0.6; font-style: italic; }
        .input-box { display: flex; background: var(--glass); border-radius: 12px; padding: 10px; margin-top: 20px; width: 100%; }
        input { flex: 1; background: transparent; border: none; color: white; padding: 10px; outline: none; }
        .file-item { padding: 10px; border-radius: 8px; cursor: pointer; margin-bottom: 5px; background: rgba(255,255,255,0.02); }
        .file-item:hover { background: var(--glass); }
        #editor { width: 100%; height: 80%; background: transparent; color: #94a3b8; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 10px; outline: none; }
        button { background: var(--accent); border: none; color: white; border-radius: 8px; padding: 8px 15px; cursor: pointer; }
    </style>
</head>
<body>
    <div class="app">
        <div class="panel" id="side">
            <h3>KNOWLEDGE</h3>
            <div id="fileList"></div>
        </div>
        <div class="chat-view">
            <div class="chat-inner">
                <div class="messages" id="msgs"></div>
                <div class="input-box">
                    <input id="in" placeholder="Ask your agent to search or edit files...">
                    <button onclick="send()">Send</button>
                </div>
            </div>
        </div>
        <div class="panel" id="edit">
            <div style="display:flex; justify-content:space-between; margin-bottom:10px">
                <span id="fn">Untitled</span>
                <button onclick="save()">Save</button>
            </div>
            <textarea id="editor"></textarea>
        </div>
    </div>
    <script>
        let conv = [];
        async function send() {
            const input = document.getElementById('in'); const q = input.value; if(!q) return;
            input.value = ''; addM(q, 'user');
            conv.push({role: "user", content: q});
            
            const r = await fetch('/api/chat', {method: 'POST', body: JSON.stringify({messages: conv})});
            const reader = r.body.getReader(); const dec = new TextDecoder();
            let aiMsg = addM('Thinking...', 'ai'); let full = '';
            
            while(true) {
                const {done, value} = await reader.read(); if(done) break;
                const lines = dec.decode(value).split('\\n');
                for(let l of lines) {
                    if(!l) continue; const d = JSON.parse(l);
                    if(d.message.role === 'system') addM(d.message.content, 'sys');
                    else if(d.message.content) { full += d.message.content; aiMsg.innerHTML = marked.parse(full); }
                }
            }
            conv.push({role: "assistant", content: full});
            fetchFiles();
        }
        function addM(t, r) {
            const d = document.createElement('div'); d.className = 'msg ' + r; d.innerHTML = marked.parse(t);
            const m = document.getElementById('msgs'); m.appendChild(d); m.scrollTop = m.scrollHeight; return d;
        }
        async function fetchFiles() {
            const r = await fetch('/api/files'); const d = await r.json();
            const l = document.getElementById('fileList'); l.innerHTML = '';
            d.files.forEach(f => {
                const i = document.createElement('div'); i.className = 'file-item'; i.textContent = f;
                i.onclick = async () => {
                    const fr = await fetch('/api/read-file', {method: 'POST', body: JSON.stringify({filename: f})});
                    const fd = await fr.json(); document.getElementById('editor').value = fd.content;
                    document.getElementById('fn').textContent = f;
                };
                l.appendChild(i);
            });
        }
        fetchFiles();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), AgenticHandler) as httpd:
        print(f"Agentic Dashboard on http://localhost:{PORT}")
        httpd.serve_forever()
