from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from mangum import Mangum
import secrets

app = FastAPI()

app.add_middleware(
    SessionMiddleware,
    secret_key="change_this_secret_key"
)

# In-memory storage variables (Note: Serverless functions reset state between cold starts)
rooms = {}          # invite -> room_id
room_files = {}     # room_id -> {filename: content}
room_chats = {}     # room_id -> [{user, message}, ...]
connections = {}    # room_id -> [{ws, user}, ...]

LOGIN_PAGE = """
<!DOCTYPE html>
<html>
<head>
<title>Login</title>
<style>
body{
background:#111;
color:white;
font-family:Arial;
display:flex;
justify-content:center;
align-items:center;
height:100vh;
}
form{
background:#222;
padding:30px;
border-radius:10px;
}
input{
padding:10px;
width:250px;
margin-bottom:10px;
}
button{
padding:10px;
width:100%;
}
</style>
</head>
<body>
<form method="post">
<h2>Demo Login</h2>
<input name="username" placeholder="Username" required>
<br>
<button>Login</button>
</form>
</body>
</html>
"""

DASHBOARD = """
<!DOCTYPE html>
<html>
<head>
<title>Dashboard</title>
<style>
body{
background:#181818;
color:white;
font-family:Arial;
padding:40px;
}
button,input{
padding:8px 12px;
margin:5px 0;
}
.room-list{
background:#222;
padding:15px;
border-radius:8px;
margin-top:20px;
max-width:550px;
}
ul{ padding-left:20px; }
li{ margin-bottom:12px; }
a{ color:#4ec9b0; text-decoration:none; }
a:hover{ text-decoration:underline; }
.delete-btn{
background:#d9534f;
color:white;
border:none;
padding:4px 8px;
border-radius:4px;
cursor:pointer;
font-size:12px;
margin-left:10px;
}
.delete-btn:hover{
background:#c9302c;
}
</style>
</head>
<body>

<h2>Hello {username}</h2>

<form action="/create" method="post">
<button>Create Room</button>
</form>

<hr>

<form action="/join" method="post">
<input name="code" placeholder="Invite Code" required>
<button>Join</button>
</form>

<div class="room-list">
<h3>Saved / Active Rooms</h3>
<ul>
__SAVED_ROOMS__
</ul>
</div>

</body>
</html>
"""

ROOM_HTML = """
<!DOCTYPE html>
<html>
<head>
<title>Room - Collaborative IDE</title>
<script src="https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs/loader.js"></script>
<style>
body{
margin:0;
background:#121212;
color:white;
font-family:Arial;
display:flex;
height:100vh;
overflow:hidden;
}

#left-panel{
width:260px;
background:#1e1e1e;
padding:15px;
display:flex;
flex-direction:column;
border-right: 1px solid #333;
}

#code-section{
flex:1;
display:flex;
flex-direction:column;
background:#181818;
}

#top-bar{
display:flex;
align-items:center;
justify-content:space-between;
background:#202020;
padding:8px 15px;
border-bottom:1px solid #333;
}

#tabs{
display:flex;
gap:5px;
overflow-x:auto;
flex:1;
margin-right: 10px;
}

.tab{
background:#2d2d2d;
padding:6px 12px;
cursor:pointer;
border-radius:4px 4px 0 0;
font-size:13px;
border:1px solid #3d3d3d;
border-bottom:none;
white-space:nowrap;
}

.tab.active{
background:#1e1e1e;
border-color:#007acc;
color:#fff;
}

#editor-container{
flex:1;
position:relative;
}

#chat-section{
width:350px;
background:#202020;
display:flex;
flex-direction:column;
border-left: 1px solid #333;
}

#messages{
flex:1;
overflow-y:auto;
padding:15px;
word-break:break-word;
font-size:13px;
}

.code-ref{
color: #4ec9b0;
cursor: pointer;
text-decoration: underline;
font-weight: bold;
}

#bottom{
display:flex;
padding:10px;
background:#181818;
border-top:1px solid #333;
}

input, button, select{
padding:8px;
}

#msg{
flex:1;
background:#2a2a2a;
border:1px solid #444;
color:white;
border-radius:4px;
}

button{
background:#007acc;
color:white;
border:none;
cursor:pointer;
border-radius:4px;
}

button:hover{
background:#005999;
}

select{
background:#2a2a2a;
color:white;
border:1px solid #444;
border-radius:4px;
}

.file-form{
display:flex;
gap:5px;
margin-top:10px;
}
.file-form input{
flex:1;
padding:6px;
background:#2a2a2a;
border:1px solid #444;
color:white;
border-radius:4px;
}
</style>
</head>
<body>

<!-- Left Sidebar -->
<div id="left-panel">
<h3>Invite Code</h3>
<div style="background:#2a2a2a; padding:8px; font-family:monospace; font-size:14px; border-radius:4px;">__CODE__</div>

<h3>Files</h3>
<div class="file-form">
  <input id="new-filename" placeholder="filename.py">
  <button onclick="createFile()">Add</button>
</div>

<h3>Online Users</h3>
<ul id="users" style="padding-left:15px; font-size:14px;"></ul>
<br>
<a href="/dashboard" style="color:#007acc; text-decoration:none;">&larr; Back to Dashboard</a>
</div>

<!-- Middle Section: Monaco Editor -->
<div id="code-section">
  <div id="top-bar">
    <div id="tabs"></div>
    <div>
      <label style="font-size:12px; color:#aaa;">Language:</label>
      <select id="syntax-select" onchange="changeLanguage()">
        <option value="python" selected>Python</option>
        <option value="javascript">JavaScript</option>
        <option value="html">HTML</option>
        <option value="css">CSS</option>
        <option value="cpp">C++</option>
      </select>
    </div>
  </div>
  
  <div id="editor-container"></div>
</div>

<!-- Right Sidebar: Chat Area -->
<div id="chat-section">
<div style="padding:12px; background:#181818; border-bottom:1px solid #333;">
  <h3 style="margin:0;">Room Chat</h3>
  <small style="color:#888;">Catch up on previous chat history</small>
</div>
<div id="messages"></div>

<div id="bottom">
<input id="msg" placeholder="Type message..." onkeydown="if(event.key==='Enter') sendChat()">
<button onclick="sendChat()">Send</button>
</div>
</div>

<script>
const USERNAME = "__USERNAME__";
const protocol = location.protocol === "https:" ? "wss://" : "ws://";
let ws;
try {
    ws = new WebSocket(protocol + location.host + "/ws/__ROOM__");
} catch(e) {
    console.log("WebSockets not supported in this serverless environment.");
}

let files = {};
let currentFile = "main.py";
let editor;
let decorationsCollection = null;
let isRemoteUpdate = false;
let editorInitialized = false;

require.config({
    paths: { vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.52.2/min/vs" }
});

require(["vs/editor/editor.main"], function () {
    editor = monaco.editor.create(document.getElementById("editor-container"), {
        value: "",
        language: "python",
        theme: "vs-dark",
        automaticLayout: true,
        minimap: { enabled: true },
        fontSize: 14,
        fontFamily: "Consolas, 'Courier New', monospace",
        wordWrap: "on",
        tabSize: 4,
        autoIndent: "advanced",
        formatOnPaste: true,
        formatOnType: true
    });

    decorationsCollection = editor.createDecorationsCollection();
    editorInitialized = true;
    updateEditorContent();

    editor.onDidChangeModelContent(() => {
        if (isRemoteUpdate) return;
        let content = editor.getValue();
        files[currentFile] = content;
        
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({
                type: "code_update",
                file: currentFile,
                content: content
            }));
        }
    });
});

if (ws) {
    ws.onopen = () => {
        ws.send(JSON.stringify({type: "login", user: USERNAME}));
    };

    ws.onmessage = (e) => {
        let data = JSON.parse(e.data);

        if(data.type === "init"){
            files = data.files;
            if(!files[currentFile]) {
                currentFile = Object.keys(files)[0] || "main.py";
            }
            renderTabs();
            updateEditorContent();

            let msgBox = document.getElementById("messages");
            msgBox.innerHTML = "";
            if(data.history && Array.isArray(data.history)){
                data.history.forEach(chat => {
                    appendChatMessage(chat.user, chat.message);
                });
            }
        }

        if(data.type === "sync_files"){
            files = data.files;
            if(!files[currentFile]) {
                currentFile = Object.keys(files)[0] || "main.py";
            }
            renderTabs();
            updateEditorContent();
        }

        if(data.type === "chat"){
            appendChatMessage(data.user, data.message);
        }

        if(data.type === "users"){
            users.innerHTML = "";
            data.users.forEach(u => {
                let li = document.createElement("li");
                li.innerText = u;
                users.appendChild(li);
            });
        }

        if(data.type === "room_deleted"){
            alert("This session/room has been deleted by the admin.");
            window.location.href = "/dashboard";
        }
    };
}

function appendChatMessage(user, message){
    let msgBox = document.getElementById("messages");
    let d = document.createElement("div");
    d.style.marginBottom = "6px";
    
    let messageText = message.replace(/@Line\s(\d+)/g, '<span class="code-ref" onclick="jumpAndHighlightLine($1)">@Line $1</span>');
    
    d.innerHTML = "<b>" + user + "</b>: " + messageText;
    msgBox.appendChild(d);
    msgBox.scrollTop = msgBox.scrollHeight;
}

function renderTabs(){
    let tabsContainer = document.getElementById("tabs");
    tabsContainer.innerHTML = "";
    Object.keys(files).forEach(filename => {
        let tab = document.createElement("div");
        tab.className = "tab " + (filename === currentFile ? "active" : "");
        tab.innerText = filename;
        tab.onclick = () => switchFile(filename);
        tabsContainer.appendChild(tab);
    });
}

function switchFile(filename){
    currentFile = filename;
    renderTabs();
    updateEditorContent();
    
    if (editor) {
        let ext = filename.split('.').pop();
        let lang = "python";
        if (ext === "js") lang = "javascript";
        else if (ext === "html") lang = "html";
        else if (ext === "css") lang = "css";
        else if (ext === "cpp" || ext === "h") lang = "cpp";
        
        monaco.editor.setModelLanguage(editor.getModel(), lang);
        document.getElementById("syntax-select").value = lang;
    }
}

function updateEditorContent(){
    if (!editorInitialized || !editor) return;
    let activeContent = files[currentFile] || "";
    if(editor.getValue() !== activeContent){
        isRemoteUpdate = true;
        editor.setValue(activeContent);
        isRemoteUpdate = false;
    }
}

function jumpAndHighlightLine(lineNum){
    if (!editor) return;
    editor.revealLineInCenter(lineNum);
    editor.setPosition({ lineNumber: lineNum, column: 1 });
    editor.focus();

    if (decorationsCollection) {
        decorationsCollection.set([
            {
                range: new monaco.Range(lineNum, 1, lineNum, 1),
                options: {
                    isWholeLine: true,
                    className: 'myLineDecoration',
                    glyphMarginClassName: 'myGlyphDecoration'
                }
            }
        ]);

        setTimeout(() => {
            decorationsCollection.set([]);
        }, 2000);
    }
}

const styleTag = document.createElement('style');
styleTag.innerHTML = `
    .myLineDecoration {
        background-color: rgba(0, 122, 204, 0.35) !important;
    }
`;
document.head.appendChild(styleTag);

function changeLanguage(){
    let select = document.getElementById("syntax-select");
    let lang = select.value;
    if (editor) {
        monaco.editor.setModelLanguage(editor.getModel(), lang);
    }
}

function createFile(){
    let input = document.getElementById("new-filename");
    let filename = input.value.trim();
    if(!filename) return;
    if(files[filename]) {
        alert("File already exists!");
        return;
    }
    files[filename] = "// New file context\\n";
    input.value = "";
    switchFile(filename);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: "file_create",
            file: filename,
            content: files[filename]
        }));
    }
}

function sendChat(){
    let msgInput = document.getElementById("msg");
    if(!msgInput.value.trim()) return;
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: "chat",
            message: msgInput.value
        }));
    }
    msgInput.value = "";
}
</script>

</body>
</html>
"""


@app.get("/")
async def home(request: Request):
    if "username" not in request.session:
        return RedirectResponse("/login")
    return RedirectResponse("/dashboard")


@app.get("/login")
async def login():
    return HTMLResponse(LOGIN_PAGE)


@app.post("/login")
async def login_post(request: Request, username: str = Form(...)):
    request.session["username"] = username
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/dashboard")
async def dashboard(request: Request):
    if "username" not in request.session:
        return RedirectResponse("/login")

    saved_html = ""
    for invite, room_id in rooms.items():
        saved_html += f"<li>Room ID: <b>{room_id}</b> | Invite: <a href='/room/{room_id}?code={invite}'>{invite}</a> " \
                      f"<form action='/delete-room/{room_id}' method='post' style='display:inline;'><button class='delete-btn' type='submit'>Delete</button></form></li>"
    
    if not saved_html:
        saved_html = "<li>No saved rooms found. Create a new room above!</li>"

    html = DASHBOARD.replace("{username}", request.session["username"])
    html = html.replace("__SAVED_ROOMS__", saved_html)
    return HTMLResponse(html)


@app.post("/create")
async def create(request: Request):
    room = secrets.token_hex(4)
    invite = secrets.token_hex(3)

    rooms[invite] = room
    room_files[room] = {"main.py": "# Python Collaborative File\nprint('Hello Monaco IDE!')\n"}
    room_chats[room] = []

    connections[room] = []
    return RedirectResponse(f"/room/{room}?code={invite}", status_code=302)


@app.post("/delete-room/{room_id}")
async def delete_room(request: Request, room_id: str):
    if "username" not in request.session:
        return RedirectResponse("/login")

    invite_to_remove = None
    for invite, r_id in rooms.items():
        if r_id == room_id:
            invite_to_remove = invite
            break
    if invite_to_remove:
        rooms.pop(invite_to_remove, None)

    room_files.pop(room_id, None)
    room_chats.pop(room_id, None)

    if room_id in connections:
        for client in connections[room_id]:
            try:
                await client["ws"].send_json({"type": "room_deleted"})
            except:
                pass
        connections.pop(room_id, None)

    return RedirectResponse("/dashboard", status_code=302)


@app.post("/join")
async def join(request: Request, code: str = Form(...)):
    if code not in rooms:
        return HTMLResponse("Invalid invite code. <a href='/dashboard'>Go Back</a>")

    room = rooms[code]
    return RedirectResponse(f"/room/{room}?code={code}", status_code=302)


@app.get("/room/{room}")
async def room(request: Request, room: str, code: str):
    if "username" not in request.session:
        return RedirectResponse("/login")

    html = ROOM_HTML
    html = html.replace("__ROOM__", room)
    html = html.replace("__CODE__", code)
    html = html.replace("__USERNAME__", request.session["username"])

    return HTMLResponse(html)


@app.websocket("/ws/{room}")
async def websocket_endpoint(websocket: WebSocket, room: str):
    await websocket.accept()

    if room not in connections:
        connections[room] = []
    if room not in room_files:
        room_files[room] = {"main.py": "# Python Collaborative File\n"}
    if room not in room_chats:
        room_chats[room] = []

    username = "Anonymous"
    client = {"ws": websocket, "user": username}
    connections[room].append(client)

    async def update_users():
        if room not in connections:
            return
        users = [c["user"] for c in connections[room]]
        for c in connections[room]:
            try:
                await c["ws"].send_json({"type": "users", "users": users})
            except:
                pass

    try:
        await websocket.send_json({
            "type": "init",
            "files": room_files[room],
            "history": room_chats[room]
        })

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "login":
                username = data.get("user", "Anonymous")
                client["user"] = username
                await update_users()

            elif msg_type == "chat":
                chat_msg = {
                    "user": username,
                    "message": data.get("message")
                }
                room_chats[room].append(chat_msg)

                for c in connections[room]:
                    await c["ws"].send_json({
                        "type": "chat",
                        "user": username,
                        "message": data.get("message")
                    })

            elif msg_type == "code_update" or msg_type == "file_create":
                filename = data.get("file")
                content = data.get("content", "")
                room_files[room][filename] = content

                for c in connections[room]:
                    if c["ws"] != websocket:
                        try:
                            await c["ws"].send_json({
                                "type": "sync_files",
                                "files": room_files[room]
                            })
                        except:
                            pass

    except WebSocketDisconnect:
        if room in connections:
            connections[room] = [c for c in connections[room] if c["ws"] != websocket]
            if len(connections[room]) == 0:
                connections.pop(room, None)
            else:
                await update_users()

# Mangum handler for Vercel serverless functions
handler = Mangum(app)
