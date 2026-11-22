import os
import time
import uuid
from flask import Flask, render_template_string, request, send_from_directory, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # Максимум 100 МБ на загрузку
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
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #fff; max-width: 600px; margin: 0 auto; padding: 16px; }
        h2 { text-align: center; margin-bottom: 20px; }
        .card { background: #1e1e1e; padding: 16px; border-radius: 12px; margin-bottom: 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        .row { display: flex; gap: 10px; align-items: center; }
        input[type="file"] { flex: 1; color: #ccc; font-size: 14px; }
        button { background: #1db954; color: #fff; border: none; padding: 10px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: 0.2s; }
        button:hover { background: #1ed760; }
        button:disabled { background: #555; cursor: not-allowed; }
        .btn-sec { background: #333; padding: 10px 14px; }
        .btn-sec:hover { background: #444; }
        .btn-del { background: #e53935; padding: 6px 10px; font-size: 12px; margin-left: 8px; }
        .btn-del:hover { background: #f44336; }
        
        .now-playing-box { text-align: center; margin-bottom: 14px; }
        #nowTitle { font-size: 18px; font-weight: bold; color: #1db954; word-break: break-word; }
        #nowArtist { font-size: 14px; color: #b3b3b3; margin-top: 4px; }
        
        audio { width: 100%; margin-bottom: 12px; border-radius: 8px; }
        .controls { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }
        .hint { font-size: 12px; color: #888; text-align: center; margin-top: 12px; }
        
        .playlist { list-style: none; padding: 0; margin: 0; }
        .track { display: flex; justify-content: space-between; align-items: center; background: #1e1e1e; padding: 12px; margin-bottom: 8px; border-radius: 8px; border-left: 4px solid transparent; transition: 0.2s; }
        .track:hover { background: #252525; }
        .track.active { border-left-color: #1db954; background: #282828; }
        .track-info { flex: 1; cursor: pointer; padding-right: 10px; overflow: hidden; }
        .track-title { font-weight: 600; font-size: 15px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .track-artist { font-size: 12px; color: #aaa; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
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
        <div class="now-playing-box">
            <div id="nowTitle">Плейлист пуст</div>
            <div id="nowArtist">Загрузите музыку, чтобы начать</div>
        </div>
        <audio id="player" controls playsinline></audio>
        <div class="controls">
            <button class="btn-sec" onclick="socket.emit('prev_track')">⏮ Назад</button>
            <button class="btn-sec" onclick="socket.emit('request_sync')">🔄 Синхронизировать</button>
            <button class="btn-sec" onclick="socket.emit('next_track')">Вперед ⏭</button>
        </div>
        <div class="hint">На телефоне нажмите Play один раз при входе, чтобы браузер разрешил автозапуск</div>
    </div>

    <ul class="playlist" id="playlist"></ul>

    <script src="https://socket.io"></script>
    <script>
        const socket = io();
        const player = document.getElementById('player');
        const playlistEl = document.getElementById('playlist');
        const nowTitleEl = document.getElementById('nowTitle');
        const nowArtistEl = document.getElementById('nowArtist');
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
            for (let file of input.files) {
                formData.append('files', file);
            }
            
            try {
                const res = await fetch('/upload', { method: 'POST', body: formData });
                if (!res.ok) throw new Error();
                input.value = '';
            } catch (e) {
                alert('Ошибка загрузки файла. Проверьте размер или формат.');
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
                
                const infoDiv = document.createElement('div');
                infoDiv.className = 'track-info';
                infoDiv.onclick = () => socket.emit('select_track', index);
                
                const titleDiv = document.createElement('div');
                titleDiv.className = 'track-title';
                titleDiv.textContent = `${index + 1}. ${track.title}`;
                
                const artistDiv = document.createElement('div');
                artistDiv.className = 'track-artist';
                artistDiv.textContent = track.artist;
                
                infoDiv.appendChild(titleDiv);
                infoDiv.appendChild(artistDiv);

                const delBtn = document.createElement('button');
                delBtn.className = 'btn-del';
                delBtn.textContent = '✕';
                delBtn.title = 'Удалить трек';
                delBtn.onclick = (e) => {
                    e.stopPropagation();
                    socket.emit('delete_track', index);
                };

                li.appendChild(infoDiv);
                li.appendChild(delBtn);
                playlistEl.appendChild(li);
            });
        }

        socket.on('state_update', (state) => {
            currentState = state;
            renderPlaylist();
            
            if (state.current_index >= 0 && state.playlist[state.current_index]) {
                const track = state.playlist[state.current_index];
                nowTitleEl.textContent = '▶ ' + track.title;
                nowArtistEl.textContent = track.artist;
                
                if (currentTrackId !== track.id) {
                    currentTrackId = track.id;
                    isRemoteAction = true;
                    player.src = '/uploads/' + track.filename;
                    player.currentTime = state.timestamp;
                    if (state.is_playing) {
                        player.play().catch(() => {});
                    }
                } else {
                    isRemoteAction = true;
                    if (Math.abs(player.currentTime - state.timestamp) > 1.5) {
                        player.currentTime = state.timestamp;
                    }
                    if (state.is_playing && player.paused) {
                        player.play().catch(() => {});
                    } else if (!state.is_playing && !player.paused) {
                        player.pause();
                    }
                }
            } else {
                currentTrackId = null;
                nowTitleEl.textContent = 'Плейлист пуст';
                nowArtistEl.textContent = 'Загрузите музыку, чтобы начать';
                player.pause();
                player.removeAttribute('src');
                player.load();
            }
        });

        socket.on('sync_playback', (data) => {
            isRemoteAction = true;
            if (Math.abs(player.currentTime - data.time) > 1.0) {
                player.currentTime = data.time;
            }
            if (data.action === 'play') {
                player.play().catch(() => {});
            } else if (data.action === 'pause') {
                player.pause();
            }
        });

        player.onplay = () => {
            if (!isRemoteAction) {
                socket.emit('playback', { action: 'play', time: player.currentTime });
            }
            isRemoteAction = false;
        };

        player.onpause = () => {
            if (!isRemoteAction) {
                socket.emit('playback', { action: 'pause', time: player.currentTime });
            }
            isRemoteAction = false;
        };

        player.onseeked = () => {
            if (!isRemoteAction) {
                socket.emit('playback', { action: 'seek', time: player.currentTime });
            }
            isRemoteAction = false;
        };

