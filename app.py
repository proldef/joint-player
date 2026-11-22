try:
    from gevent import monkey
    monkey.patch_all()
except ImportError:
    pass

import os
import time
import uuid
import random
import urllib.parse

import requests
from flask import (
    Flask, request, send_from_directory, jsonify, redirect, Response
)
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

AUDIO_EXTS = ('.mp3', '.wav', '.ogg', '.m4a', '.flac', '.aac', '.opus')
YDISK_API = "https://cloud-api.yandex.net/v1/disk/public/resources"
YDISK_DOWNLOAD_API = "https://cloud-api.yandex.net/v1/disk/public/resources/download"

state = {
    'playlist': [],
    'current_index': -1,
    'is_playing': False,
    'timestamp': 0.0,
    'last_update': time.time()
}


def get_current_state():
    current_ts = state['timestamp']
    if state['is_playing'] and state['current_index'] >= 0:
        current_ts += (time.time() - state['last_update'])
    return {
        'playlist': state['playlist'],
        'current_index': state['current_index'],
        'is_playing': state['is_playing'],
        'timestamp': current_ts
    }


def broadcast_state():
    socketio.emit('state_update', get_current_state())


def parse_filename(filename):
    """'Артист - Название.mp3' -> (название, артист)"""
    name = os.path.splitext(filename)[0]
    if ' - ' in name:
        parts = name.split(' - ', 1)
        return parts[1].strip(), parts[0].strip()
    return name.strip(), 'Неизвестный исполнитель'


def start_track(index):
    state['current_index'] = index
    state['timestamp'] = 0.0
    state['is_playing'] = True
    state['last_update'] = time.time()


def remove_local_file(track):
    if 'local_file' in track:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], track['local_file'])
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass


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
        input[type="text"], input[type="file"] { flex: 1; background: #2a2a2a; border: 1px solid #333; color: #fff; padding: 10px; border-radius: 8px; font-size: 14px; min-width: 0; }
        button { background: #1db954; color: #fff; border: none; padding: 10px 14px; border-radius: 8px; font-weight: bold; cursor: pointer; white-space: nowrap; transition: 0.2s; }
        button:hover { background: #1ed760; }
        button:disabled { background: #555; cursor: not-allowed; }
        .btn-sec { background: #333; }
        .btn-sec:hover { background: #444; }
        .btn-shuffle { background: #2b5b3c; border: 1px solid #1db954; }
        .btn-shuffle:hover { background: #1db954; }
        .btn-del { background: #e53935; padding: 6px 10px; font-size: 12px; margin-left: 8px; }
        .btn-del:hover { background: #ef5350; }

        .now-playing-box { text-align: center; margin-bottom: 14px; }
        #nowTitle { font-size: 18px; font-weight: bold; color: #1db954; word-break: break-word; }
        #nowArtist { font-size: 14px; color: #b3b3b3; margin-top: 4px; }

        audio { width: 100%; margin-bottom: 12px; }
        .controls { display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
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
            <button id="ydiskBtn" onclick="importYdisk()">С Диска</button>
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
            <div id="nowArtist">Добавьте музыку с устройства или Яндекс.Диска</div>
        </div>
        <audio id="player" controls playsinline></audio>
        <div class="controls">
            <button class="btn-sec" onclick="socket.emit('prev_track')">⏮ Назад</button>
            <button class="btn-sec" onclick="socket.emit('request_sync')">🔄 Синхр.</button>
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

    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
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
        let ignoreEvents = false;
        let ignoreTimer = null;
        let pendingSeek = null;

        function muteEvents(ms) {
            ignoreEvents = true;
            clearTimeout(ignoreTimer);
            ignoreTimer = setTimeout(() => { ignoreEvents = false; }, ms);
        }

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
                alert('Ошибка загрузки файла (возможно, превышен лимит 100 МБ).');
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

        socket.on('state_update', (newState) => {
            currentState = newState;
            renderPlaylist();

            const track = newState.playlist[newState.current_index];
            if (newState.current_index >= 0 && track) {
                nowTitleEl.textContent = track.title;
                nowArtistEl.textContent = track.artist;
                document.title = `${track.artist} — ${track.title}`;

                muteEvents(500);

                if (currentTrackId !== track.id) {
                    currentTrackId = track.id;
                    pendingSeek = newState.timestamp;
                    player.src = track.url;
                    player.load();
                } else if (Math.abs(player.currentTime - newState.timestamp) > 1.5) {
                    player.currentTime = newState.timestamp;
                }

                if (newState.is_playing && player.paused) {
                    player.play().catch(() => {});
                } else if (!newState.is_playing && !player.paused) {
                    player.pause();
                }
            } else {
                currentTrackId = null;
                pendingSeek = null;
                nowTitleEl.textContent = 'Плейлист пуст';
                nowArtistEl.textContent = 'Добавьте музыку с устройства или Яндекс.Диска';
                document.title = 'Слушаем вместе';
                muteEvents(500);
                player.pause();
                player.removeAttribute('src');
                player.load();
            }
        });

        // Когда трек загрузился — перематываем на нужную секунду
        player.addEventListener('loadedmetadata', () => {
            if (pendingSeek !== null) {
                muteEvents(500);
                if (pendingSeek > 0.5) player.currentTime = pendingSeek;
                pendingSeek = null;
                if (currentState.is_playing && player.paused) {
                    player.play().catch(() => {});
                }
            }
        });

        player.addEventListener('play', () => {
            if (!ignoreEvents && currentTrackId) {
                socket.emit('play', { timestamp: player.currentTime });
            }
        });
        player.addEventListener('pause', () => {
            if (!ignoreEvents && currentTrackId && !player.ended) {
                socket.emit('pause', { timestamp: player.currentTime });
            }
        });
        player.addEventListener('seeked', () => {
            if (!ignoreEvents && currentTrackId) {
                socket.emit('seek', { timestamp: player.currentTime });
            }
        });
        // Отправляем id трека, чтобы сервер переключил его только ОДИН раз,
        // даже если "закончился" он у всех друзей одновременно
        player.addEventListener('ended', () => {
            if (currentTrackId) {
                socket.emit('track_ended', { id: currentTrackId });
            }
        });

        // Периодическая подстройка, если у кого-то съехало время
        setInterval(() => {
            if (currentState.is_playing && !document.hidden) {
                socket.emit('request_sync');
            }
        }, 15000);

        socket.on('connect', () => socket.emit('request_sync'));
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    return Response(HTML_PAGE, mimetype='text/html')


@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('files')
    added = False
    for f in files:
        if f and f.filename:
            orig_name = f.filename
            ext = os.path.splitext(orig_name)[1].lower()
            if ext not in AUDIO_EXTS:
                continue
            saved_name = f"{uuid.uuid4().hex}{ext}"
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], saved_name))
            title, artist = parse_filename(orig_name)
            state['playlist'].append({
                'id': uuid.uuid4().hex,
                'title': title,
                'artist': artist,
                'url': f"/uploads/{saved_name}",
                'local_file': saved_name
            })
            added = True
    if added:
        if state['current_index'] == -1:
            start_track(0)
        broadcast_state()
        return jsonify({'status': 'ok'})
    return jsonify({'error': 'Аудиофайлы не найдены'}), 400


@app.route('/import_ydisk', methods=['POST'])
def import_ydisk():
    data = request.get_json(silent=True) or {}
    public_url = data.get('url', '').strip()
    if not public_url:
        return jsonify({'error': 'Укажите ссылку'}), 400

    try:
        res = requests.get(
            YDISK_API,
            params={'public_key': public_url, 'limit': 1000},
            timeout=15
        )
        if res.status_code != 200:
            return jsonify({
                'error': 'Не удалось получить доступ к Яндекс.Диску. Убедитесь, что ссылка публичная.'
            }), 400
        meta = res.json()
    except Exception:
        return jsonify({'error': 'Ошибка соединения с Яндекс.Диском'}), 500

    items_to_add = []
    if meta.get('type') == 'file':
        name = meta.get('name', 'Трек.mp3')
        if name.lower().endswith(AUDIO_EXTS) or meta.get('media_type') == 'audio':
            items_to_add.append((name, None))
    elif meta.get('type') == 'dir':
        embedded = meta.get('_embedded', {}).get('items', [])
        for item in embedded:
            if item.get('type') == 'file':
                name = item.get('name', '')
                if name.lower().endswith(AUDIO_EXTS) or item.get('media_type') == 'audio':
                    items_to_add.append((name, item.get('path')))

    if not items_to_add:
        return jsonify({'error': 'По ссылке не найдено аудиофайлов'}), 400

    for name, path in items_to_add:
        title, artist = parse_filename(name)
        encoded_url = urllib.parse.quote(public_url, safe='')
        stream_url = f"/ydisk_stream?url={encoded_url}"
        if path:
            stream_url += f"&path={urllib.parse.quote(path, safe='')}"
        state['playlist'].append({
            'id': uuid.uuid4().hex,
            'title': title,
            'artist': artist,
            'url': stream_url
        })

    if state['current_index'] == -1 and state['playlist']:
        start_track(0)
    broadcast_state()
    return jsonify({'status': 'ok', 'added': len(items_to_add)})


@app.route('/ydisk_stream')
def ydisk_stream():
    public_url = request.args.get('url')
    path = request.args.get('path')
    if not public_url:
        return "Missing URL", 400
    params = {'public_key': public_url}
    if path:
        params['path'] = path
    try:
        res = requests.get(YDISK_DOWNLOAD_API, params=params, timeout=10)
        if res.status_code == 200:
            href = res.json().get('href')
            if href:
                return redirect(href)
    except Exception:
        pass
    return "Failed to get stream", 502


# ---------------- Socket.IO события ----------------

@socketio.on('connect')
def handle_connect():
    emit('state_update', get_current_state())


@socketio.on('request_sync')
def handle_request_sync():
    emit('state_update', get_current_state())


@socketio.on('play')
def handle_play(data=None):
    if state['current_index'] < 0:
        return
    state['is_playing'] = True
    if data and 'timestamp' in data:
        state['timestamp'] = float(data['timestamp'])
    state['last_update'] = time.time()
    broadcast_state()


@socketio.on('pause')
def handle_pause(data=None):
    if state['current_index'] < 0:
        return
    if data and 'timestamp' in data:
        state['timestamp'] = float(data['timestamp'])
    elif state['is_playing']:
        state['timestamp'] += (time.time() - state['last_update'])
    state['is_playing'] = False
    state['last_update'] = time.time()
    broadcast_state()


@socketio.on('seek')
def handle_seek(data=None):
    if state['current_index'] < 0 or not data or 'timestamp' not in data:
        return
    state['timestamp'] = float(data['timestamp'])
    state['last_update'] = time.time()
    broadcast_state()


@socketio.on('select_track')
def handle_select_track(index):
    if isinstance(index, int) and 0 <= index < len(state['playlist']):
        start_track(index)
        broadcast_state()


@socketio.on('next_track')
def handle_next_track():
    if not state['playlist']:
        return
    start_track((state['current_index'] + 1) % len(state['playlist']))
    broadcast_state()


@socketio.on('prev_track')
def handle_prev_track():
    if not state['playlist']:
        return
    start_track((state['current_index'] - 1) % len(state['playlist']))
    broadcast_state()


@socketio.on('track_ended')
def handle_track_ended(data=None):
    """Переключаем трек только если сообщение пришло про текущий трек
    (иначе при нескольких слушателях трек перескакивал бы несколько раз)."""
    if not state['playlist'] or state['current_index'] < 0 or not data:
        return
    current = state['playlist'][state['current_index']]
    if data.get('id') != current['id']:
        return
    start_track((state['current_index'] + 1) % len(state['playlist']))
    broadcast_state()


@socketio.on('shuffle_playlist')
def handle_shuffle_playlist():
    if len(state['playlist']) <= 1:
        return
    current_track = None
    if 0 <= state['current_index'] < len(state['playlist']):
        current_track = state['playlist'][state['current_index']]
    random.shuffle(state['playlist'])
    if current_track:
        for i, t in enumerate(state['playlist']):
            if t['id'] == current_track['id']:
                state['current_index'] = i
                break
    broadcast_state()


@socketio.on('delete_track')
def handle_delete_track(index):
    if not isinstance(index, int) or not (0 <= index < len(state['playlist'])):
        return
    removed = state['playlist'].pop(index)
    remove_local_file(removed)

    if not state['playlist']:
        state['current_index'] = -1
        state['is_playing'] = False
        state['timestamp'] = 0.0
    elif index < state['current_index']:
        state['current_index'] -= 1
    elif index == state['current_index']:
        # удалили играющий трек — начинаем следующий
        if state['current_index'] >= len(state['playlist']):
            state['current_index'] = 0
        state['timestamp'] = 0.0
    state['last_update'] = time.time()
    broadcast_state()


@socketio.on('clear_playlist')
def handle_clear_playlist():
    for track in state['playlist']:
        remove_local_file(track)
    state['playlist'] = []
    state['current_index'] = -1
    state['is_playing'] = False
    state['timestamp'] = 0.0
    state['last_update'] = time.time()
    broadcast_state()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port)
