import os
import time
import uuid
import random
import requests
from flask import Flask, render_template_string, request, send_from_directory, jsonify, redirect
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
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #fff; max-width: 650px; margin: 0 auto; padding: 16px; }
        h2 { text-align: center; margin-bottom: 16px; }
        .card { background: #1e1e1e; padding: 16px; border-radius: 12px; margin-bottom: 14px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        .row { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
        .row:last-child { margin-bottom: 0; }
        input[type="text"], input[type="file"] { flex: 1; background: #2a2a2a; border: 1px solid #333; color: #fff; padding: 10px; border-radius: 8px; font-size: 14px; }
        button { background: #1db954; color: #fff; border: none; padding: 10px 14px; border-radius: 8px; font-weight: bold; cursor: pointer; white-space: nowrap; transition: 0.2s; }
        button:hover { background: #1ed760; }
        button:disabled { background: #555; cursor: not-allowed; }
        .btn-sec { background: #333; }
        .btn-sec:hover { background: #444; }
        .btn-shuffle { background: #2b5b3c; border: 1px solid #1db954; }
        .btn-shuffle:hover { background: #1db954; }
        .btn-del { background: #e53935; padding: 6px 10px; font-size: 12px; margin-left: 8px; }
        
        .now-playing-box { text-align: center; margin-bottom: 14px; }
        #nowTitle { font-size: 18px; font-weight: bold; color: #1db954; word-break: break-word; }
        #nowArtist { font-size: 14px; color: #b3b3b3; margin-top: 4px; }
        
        audio { width: 100%; margin-bottom: 12px; }
        .controls { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }
        .hint { font-size: 12px; color: #888; text-align: center; margin-top: 10px; }
        
        .playlist-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; font-size: 14px; color: #aaa; }
        .playlist { list-style: none; padding: 0; margin: 0; max-height: 450px; overflow-y: auto; }
        .track { display: flex; justify-content: space-between; align-items: center; background: #1e1e1e; padding: 10px 12px; margin-bottom: 6px; border-radius: 8px; border-left: 4px solid transparent; }
        .track:hover { background: #252525; }
        .track.active { border-left-color: #1db954; background: #282828; }
        .track-info { flex: 1; cursor: pointer; padding-right: 10px; overflow: hidden; }
        .track-title { font-weight: 600; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .track-artist { font-size: 12px; color: #aaa; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        #status { font-size: 13px; color: #1db954; margin-top: 8px; text-align: center; display: none; }
    </style>
</head>
<body>
    <h2>🎧 Совместный плеер</h2>
    
    <div class="card">
        <div class="row">
            <input type="text" id="ydiskUrl" placeholder="Ссылка на публичную папку или файл Яндекс.Диска">
            <button id="ydiskBtn" onclick="importYdisk()">Добавить с Диска</button>
        </div>
        <div class="row">
            <input type="file" id="fileInput" accept="audio/*" multiple>
            <button id="uploadBtn" class="btn-sec" onclick="uploadFiles()">С устройства</button>
        </div>
        <div id="status">Загружаем треки...</div>
    </div>

    <div class="card">
        <div class="now-playing-box">
            <div id="nowTitle">Плейлист пуст</div>
            <div id="nowArtist">Вставьте ссылку на папку Яндекс.Диска с музыкой</div>
        </div>
        <audio id="player" controls playsinline></audio>
        <div class="controls">
            <button class="btn-sec" onclick="socket.emit('prev_track')">⏮ Назад</button>
            <button class="btn-sec" onclick="socket.emit('request_sync')">🔄 Синхронизировать</button>
            <button class="btn-sec" onclick="socket.emit('next_track')">Вперед ⏭</button>
            <button class="btn-shuffle" onclick="socket.emit('shuffle_playlist')">🔀 Перемешать</button>
        </div>
        <div class="hint">На телефоне нажмите Play один раз при входе, чтобы браузер разрешил автопереключение</div>
    </div>

    <div class="playlist-header">
        <span id="trackCount">Треков в очереди: 0</span>
        <button class="btn-del" onclick="if(confirm('Очистить весь плейлист?')) socket.emit('clear_playlist')">Очистить всё</button>
    </div>
    <ul class="playlist" id="playlist"></ul>

    <script src="https://socket.io"></script>
    <script>
        const socket = io();
        const player = document.getElementById('player');
        const playlistEl = document.getElementById('playlist');
        const nowTitleEl = document.getElementById('nowTitle');
        const nowArtistEl = document.getElementById('nowArtist');
        const trackCountEl = document.getElementById('trackCount');
        const statusEl = document.getElementById('status');

        let currentState = { playlist: [], current_index: -1 };
        let currentTrackId = null;
        let isRemoteAction = false;

        async function importYdisk() {
            const input = document.getElementById('ydiskUrl');
            const btn = document.getElementById('ydiskBtn');
            const url = input.value.trim();
            if (!url) return;

            btn.disabled = true;
            statusEl.textContent = 'Импортируем треки с Яндекс.Диска...';
            statusEl.style.display = 'block';

            try {
                const res = await fetch('/import_ydisk', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || 'Ошибка импорта');
                input.value = '';
            } catch (e) {
                alert(e.message);
            } finally {
                btn.disabled = false;
                statusEl.style.display = 'none';
            }
        }

        async function uploadFiles() {
            const input = document.getElementById('fileInput');
            const btn = document.getElementById('uploadBtn');
            if (!input.files.length) return;
            btn.disabled = true;
            statusEl.textContent = 'Загружаем файлы...';
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
                btn.disabled = false;
                statusEl.style.display = 'none';
            }
        }

        function renderPlaylist() {
            playlistEl.innerHTML = '';
            trackCountEl.textContent = `Треков в очереди: ${currentState.playlist.length}`;
            
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
