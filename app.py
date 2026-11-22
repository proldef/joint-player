import os
import time
import uuid
from flask import Flask, render_template_string, request, send_from_directory, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

state = {
    'playlist': [],
    'current_index': -1,
    'is_playing': False,
    'timestamp': 0.0,
    'last_update': time.time()
}

HTML_PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Слушаем вместе</title>
    <style>
        * { box-sizing: border-box; }
        body { font-family: sans-serif; background: #121212; color: #fff; max-width: 600px; margin: 0 auto; padding: 16px; }
        h2 { text-align: center; }
        .card { background: #1e1e1e; padding: 16px; border-radius: 12px; margin-bottom: 16px; }
        .row { display: flex; gap: 10px; align-items: center; }
        input[type="file"] { flex: 1; color: #ccc; }
        button { background: #1db954; color: #fff; border: none; padding: 10px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; }
        button:disabled { background: #555; }
        .btn-sec { background: #333; padding: 8px 12px; }
        .btn-del { background: #e53935; padding: 6px 10px; font-size: 12px; }
        #nowPlaying { font-weight: bold; margin-bottom: 12px; color: #1db954; text-align: center; word-break: break-word; }
        audio { width: 100%; margin-bottom: 10px; }
        .controls { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }
        .hint { font-size: 12px; color: #888; text-align: center; margin-top: 10px; }
        .playlist { list-style: none; padding: 0; margin: 0; }
        .track { display: flex; justify-content: space-between; align-items: center; background: #1e1e1e; padding: 12px; margin-bottom: 8px; border-radius: 8px; border-left: 4px solid transparent; }
        .track.active { border-left-color: #1db954; background: #282828; }
        .track-name { flex: 1; cursor: pointer; word-break: break-word; padding-right: 10px; }
        #status { font-size: 13px; color: #1db954; margin-top: 8px; text-align: center; display: none; }
    </style>
</head>
<body>
    <h2>🎧 Совместный плеер</h2>
    <div class="card">
        <div class="row">
            <input type="file" id="fileInput" accept="audio/*" multiple>
            <button id="uploadBtn" onclick="uploadFiles()">Загрузить</button>
        </div>
        <div id="status">Загружаем треки...</div>
    </div>
    <div class="card">
        <div id="nowPlaying">Плейлист пуст</div>
        <audio id="player" controls playsinline></audio>
        <div class="controls">
            <button class="btn-sec" onclick="socket.emit('prev_track')">⏮ Назад</button>
            <button class="btn-sec" onclick="socket.emit('request_sync')">🔄 Синхронизировать</button>
            <button class="btn-sec" onclick="socket.emit('next_track')">Вперед ⏭</button>
        </div>
        <div class="hint">На телефоне нажмите Play один раз при входе, чтобы браузер разрешил звук</div>
    </div>
    <ul class="playlist" id="playlist"></ul>

    <script src="https://socket.io"></script>
    <script>
        const socket = io();
        const player = document.getElementById('player');
        const playlistEl = document.getElementById('playlist');
        const nowPlayingEl = document.getElementById('nowPlaying');
        const uploadBtn = document.getElementById('uploadBtn');
        const statusEl = document.getElementById('status');

        let currentState = { playlist: [], current_index: -1 };
        let currentTrackId = null;
        let isRemoteAction = false;

        async function uploadFiles() {
            const input = document.getElementById('fileInput');
            if (!input.files.length) return;
            uploadBtn.disabled = true;
            statusEl.style.display = 'block';
            const formData = new FormData();
            for (let file of input.files) formData.append('files', file);
            try {
                const res = await fetch('/upload', { method: 'POST', body: formData });
                if (!res.ok) throw new Error();
                input.value = '';
            } catch (e) {
                alert('Ошибка загрузки файла.');
            } finally {
                uploadBtn.disabled = false;
                statusEl.style.display = 'none';
            }
        }

        function renderPlaylist() {
            playlistEl.innerHTML = '';
            currentState.playlist.forEach((track, index) => {
                const li = document.createElement('li');
                li.className = 'track' + (index === currentState.current_index ? ' active' : '');
                const span = document.createElement('span');
                span.className = 'track-name';
                span.textContent = `${index + 1}. ${track.name}`;
                span.onclick = () => socket.emit('select_track', index);
                const delBtn = document.createElement('button');
                delBtn.className = 'btn-del';
                delBtn.textContent = '✕';
                delBtn.onclick = () => socket.emit('delete_track', index);
                li.appendChild(span);
                li.appendChild(delBtn);
                playlistEl.appendChild(li);
            });
        }

        socket.on('state_update', (state) => {
            currentState = state;
            renderPlaylist();
            if (state.current_index >= 0 && state.playlist[state.current_index]) {
                const track = state.playlist[state.current_index];
                nowPlayingEl.textContent = '▶ ' + track.name;
                if (currentTrackId !== track.id) {
                    currentTrackId = track.id;
                    isRemoteAction = true;
                    player.src = '/uploads/' + track.filename;
                    player.currentTime = state.timestamp;
                    if (state.is_playing) player.play().catch(() => {});
                } else {
                    isRemoteAction = true;
                    if (Math.abs(player.currentTime - state.timestamp) > 1.2) player.currentTime = state.timestamp;
                    if (state.is_playing && player.paused) player.play().catch(() => {});
                    else if (!state.is_playing && !player.paused) player.pause();
                }
            } else {
                currentTrackId = null;
                nowPlayingEl.textContent = 'Плейлист пуст';
                player.pause();
                player.removeAttribute('src');
                player.load();
            }
        });

        socket.on('sync_playback', (data) => {
            isRemoteAction = true;
            if (Math.abs(player.currentTime - data.time) > 0.8) player.currentTime = data.time;
            if (data.action === 'play') player.play().catch(() => {});
            if (data.action === 'pause') player.pause();
        });

        player.onplay = () => { if (!isRemoteAction) socket.emit('playback', { action: 'play', time: player.currentTime }); isRemoteAction = false; };
        player.onpause = () => { if (!isRemoteAction) socket.emit('playback', { action: 'pause', time: player.currentTime }); isRemoteAction = false; };
        player.onseeked = () => { if (!isRemoteAction) socket.emit('playback', { action: 'seek', time: player.currentTime }); isRemoteAction = false; };
        player.onended = () => { socket.emit('next_track'); };

        setInterval(() => { fetch('/ping').catch(() => {}); }, 240000);
    </script>
</body>
</html>"""

def get_current_payload():
    current_time = state['timestamp']
    if state['is_playing']:
        current_time += (time.time() - state['last_update'])
    return {
        'playlist': state['playlist'],
        'current_index': state['current_index'],
        'is_playing': state['is_playing'],
        'timestamp': current_time
    }

def broadcast_state():
    socketio.emit('state_update', get_current_payload())

@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/ping')
def ping():
    return jsonify({'status': 'alive'})

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('files')
    for file in files:
        if file and file.filename:
            original_name = os.path.basename(file.filename)
            ext = os.path.splitext(original_name)
            safe_filename = f"{uuid.uuid4().hex}{ext}"
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], safe_filename))
            state['playlist'].append({
                'id': uuid.uuid4().hex,
                'name': original_name,
                'filename': safe_filename
            })
    if state['current_index'] == -1 and state['playlist']:
        state['current_index'] = 0
        state['timestamp'] = 0.0
        state['is_playing'] = True
        state['last_update'] = time.time()
    broadcast_state()
    return 'OK'

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@socketio.on('connect')
def handle_connect():
    emit('state_update', get_current_payload())

@socketio.on('request_sync')
def handle_request_sync():
    emit('state_update', get_current_payload())

@socketio.on('select_track')
def handle_select(index):
    if 0 <= index < len(state['playlist']):
        state['current_index'] = index
        state['timestamp'] = 0.0
        state['is_playing'] = True
        state['last_update'] = time.time()
        broadcast_state()

@socketio.on('delete_track')
def handle_delete(index):
    if 0 <= index < len(state['playlist']):
        removed = state['playlist'].pop(index)
