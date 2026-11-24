/*
 * Music for the openpanel. Plain old JavaScript: it has to run in Safari on iOS 9 (no fetch, Promise, arrow functions,
 * let, const, template literals or newer methods). The queue and the controls live on the server, one session for this
 * tablet; this script plays what the server says and tells it what the person pressed.
 */
(function () {
  var PAGE = 40;
  var PLAY_LIST_MAX = 300;
  var POLL_MS = 5000;
  var SEARCH_DELAY_MS = 400;
  // The next track is loaded this many seconds before the end of the current one, so the change needs no loading.
  var PRELOAD_SECONDS = 20;
  var RESTART_AFTER_SECONDS = 3;
  // A moment of silence. Safari lets a page play sound only after a tap; playing this on both players during the first
  // tap makes them free to start the next track later without one.
  var SILENCE = 'data:audio/mpeg;base64,//uQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//uQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//uQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
  var BASE = '/openpanel/player';

  var body = document.getElementById('music-body');
  var nav = document.getElementById('music-nav');
  var searchInput = document.getElementById('music-search');
  var messageEl = document.getElementById('music-msg');
  var bar = document.getElementById('music-bar');
  var titleEl = document.getElementById('music-title');
  var artistEl = document.getElementById('music-artist');
  var coverEl = document.getElementById('music-cover');
  var playButton = document.getElementById('music-play');
  var shuffleButton = document.getElementById('music-shuffle');
  var repeatButton = document.getElementById('music-repeat');
  var seekEl = document.getElementById('music-seek');
  var timeEl = document.getElementById('music-time');
  var players = [document.getElementById('music-a'), document.getElementById('music-b')];

  var sid = makeSid();
  var state = { status: 'stopped', index: 0, shuffle: false, repeat: 'off', version: -1, currentId: null, nextId: null, queue: [] };
  var loaded = [null, null];
  var active = 0;
  var unlocked = false;
  var dragging = false;
  var current = null;
  var stack = [];
  var searchTimer = null;
  var started = false;

  // --- small helpers -------------------------------------------------------------------------

  function makeSid() {
    var stored = null;
    try { stored = window.localStorage.getItem('homestart-panel-sid'); } catch (e) { stored = null; }
    if (stored) return stored;
    var text = 'p';
    while (text.length < 24) text += Math.floor(Math.random() * 36).toString(36);
    try { window.localStorage.setItem('homestart-panel-sid', text); } catch (e2) { /* private mode: lasts until the page closes */ }
    return text;
  }

  function extend(target, extra) {
    for (var key in extra) {
      if (Object.prototype.hasOwnProperty.call(extra, key)) target[key] = extra[key];
    }
    return target;
  }

  function query(params) {
    var parts = [];
    for (var key in params) {
      if (Object.prototype.hasOwnProperty.call(params, key) && params[key] !== undefined && params[key] !== null) {
        parts.push(encodeURIComponent(key) + '=' + encodeURIComponent(params[key]));
      }
    }
    return parts.join('&');
  }

  function request(method, url, payload, done) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, url, true);
    xhr.setRequestHeader('X-HomeStart', '1');
    if (payload) xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var data = null;
      try { data = JSON.parse(xhr.responseText); } catch (e) { data = null; }
      done(xhr.status, data);
    };
    xhr.send(payload ? JSON.stringify(payload) : null);
  }

  // Titles and names come from outside, so they are only ever written as text.
  function node(tag, className, text) {
    var el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined && text !== null) el.textContent = text;
    return el;
  }

  function clear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function say(text) {
    messageEl.textContent = text || '';
    messageEl.style.display = text ? '' : 'none';
  }

  function clock(seconds) {
    var total = Math.max(0, Math.floor(seconds || 0));
    var rest = total % 60;
    return Math.floor(total / 60) + ':' + (rest < 10 ? '0' : '') + rest;
  }

  function minutes(seconds) {
    var m = Math.round((seconds || 0) / 60);
    return m >= 60 ? Math.floor(m / 60) + ' h ' + (m % 60) + ' min' : m + ' min';
  }

  function coverUrl(albumId, size) {
    return BASE + '/cover/' + albumId + '?size=' + size;
  }

  // --- playing: two players, so the next track is ready when the current one ends -------------

  function streamUrl(id) {
    return BASE + '/stream/' + id + '?sid=' + encodeURIComponent(sid);
  }

  function tryPlay(el, onBlocked) {
    var promise = el.play();
    // Older Safari returns nothing; newer returns a promise that fails when sound is not allowed.
    if (promise && promise.catch) promise.catch(function () { if (onBlocked) onBlocked(); });
  }

  function unlock() {
    if (unlocked) return;
    unlocked = true;
    for (var i = 0; i < players.length; i++) {
      players[i].src = SILENCE;
      tryPlay(players[i]);
      players[i].pause();
      players[i].removeAttribute('src');
    }
  }

  function release(index) {
    var el = players[index];
    el.pause();
    // Without a source the connection to the server is closed.
    el.removeAttribute('src');
    el.load();
    loaded[index] = null;
  }

  function load(index, id) {
    loaded[index] = id;
    players[index].src = streamUrl(id);
    players[index].load();
  }

  function preloadNext() {
    var spare = 1 - active;
    if (state.nextId === null) {
      if (loaded[spare] !== null) release(spare);
      return;
    }
    if (loaded[spare] === state.nextId) return;
    if (loaded[spare] !== null) release(spare);
    var el = players[active];
    var remaining = isFinite(el.duration) ? el.duration - el.currentTime : Infinity;
    if (remaining < PRELOAD_SECONDS) load(spare, state.nextId);
  }

  function sync() {
    var id = state.currentId;
    if (state.status === 'stopped' || id === null) {
      release(0);
      release(1);
      showTime(0, 0);
      return;
    }
    if (loaded[active] !== id) {
      if (loaded[1 - active] === id) {
        release(active);
        active = 1 - active;
      } else {
        load(active, id);
      }
    }
    if (loaded[1 - active] !== null && loaded[1 - active] !== state.nextId) release(1 - active);
    if (state.status === 'playing') {
      if (window.HomeStartPanel && window.HomeStartPanel.stopRadio) window.HomeStartPanel.stopRadio();
      tryPlay(players[active], function () { send({ action: 'pause' }); });
    } else {
      players[active].pause();
    }
    preloadNext();
  }

  function apply(next) {
    // An older answer must not undo a newer one.
    if (next.version < state.version) return;
    // The server says current_id and next_id; the rest of this script says currentId and nextId.
    next.currentId = next.current_id;
    next.nextId = next.next_id;
    state = next;
    show();
    sync();
  }

  function send(command) {
    request('POST', BASE + '/session/command', extend({ client_id: sid }, command), function (code, data) {
      if (code === 200 && data) {
        say('');
        apply(data);
      } else if (code === 503) {
        say('Too many people are listening right now.');
      } else if (code === 404) {
        say('There is nothing to play there.');
      } else {
        say('The player could not do that.');
      }
    });
  }

  function onEnded(index) {
    if (index !== active) return;
    if (state.repeat === 'one') {
      players[active].currentTime = 0;
      tryPlay(players[active]);
      return;
    }
    var spare = 1 - active;
    if (state.nextId !== null && loaded[spare] === state.nextId && players[spare].readyState >= 2) {
      // Start the track that is ready at once; the server's answer then finds it already playing.
      var finished = active;
      active = spare;
      tryPlay(players[active]);
      release(finished);
    }
    send({ action: 'ended' });
  }

  function showTime(position, duration) {
    if (dragging) return;
    seekEl.max = String(Math.max(1, Math.floor(duration)));
    seekEl.value = String(Math.floor(position));
    timeEl.textContent = clock(position) + ' / ' + clock(duration);
  }

  function onTimeUpdate(index) {
    if (index !== active) return;
    var el = players[active];
    var track = state.queue[state.index];
    var duration = isFinite(el.duration) ? el.duration : (track && track.duration_s) || 0;
    showTime(el.currentTime, duration);
    if (state.status === 'playing') preloadNext();
  }

  function wirePlayer(index) {
    var el = players[index];
    el.addEventListener('ended', function () { onEnded(index); });
    el.addEventListener('timeupdate', function () { onTimeUpdate(index); });
    el.addEventListener('error', function () {
      if (loaded[index] === null) return;
      if (index === active) {
        var track = state.queue[state.index];
        say('Cannot play ' + (track ? track.title : 'this track'));
        send({ action: 'error' });
      } else {
        release(index);
      }
    });
  }

  // --- the bar at the bottom ----------------------------------------------------------------------

  function show() {
    var track = state.queue[state.index] || null;
    bar.style.display = track ? '' : 'none';
    titleEl.textContent = track ? track.title : '';
    artistEl.textContent = track ? track.artist + (track.album ? ' · ' + track.album : '') : '';
    clear(coverEl);
    if (track && track.has_cover && track.album_id !== null) {
      var img = document.createElement('img');
      img.src = coverUrl(track.album_id, 96);
      img.alt = '';
      coverEl.appendChild(img);
    }
    playButton.textContent = state.status === 'playing' ? 'Pause' : 'Play';
    shuffleButton.className = 'ctl' + (state.shuffle ? ' on' : '');
    repeatButton.className = 'ctl' + (state.repeat !== 'off' ? ' on' : '');
    repeatButton.textContent = state.repeat === 'one' ? 'Repeat 1' : state.repeat === 'all' ? 'Repeat all' : 'Repeat';
    markRows();
  }

  function markRows() {
    var rows = body.getElementsByTagName('li');
    for (var i = 0; i < rows.length; i++) {
      var id = rows[i].getAttribute('data-track');
      var on = id !== null && state.currentId !== null && String(state.currentId) === id;
      rows[i].className = rows[i].className.replace(/\s*now\b/, '') + (on ? ' now' : '');
    }
  }

  function play(selection, startTrackId, shuffle) {
    unlock();
    var command = extend({ action: 'play' }, selection);
    if (startTrackId) command.start_track_id = startTrackId;
    if (shuffle) command.shuffle = true;
    send(command);
  }

  document.getElementById('music-prev').onclick = function () {
    if (players[active].currentTime > RESTART_AFTER_SECONDS || state.index === 0) {
      players[active].currentTime = 0;
      return;
    }
    send({ action: 'prev' });
  };
  playButton.onclick = function () {
    unlock();
    send({ action: state.status === 'playing' ? 'pause' : 'resume' });
  };
  document.getElementById('music-stop').onclick = function () { send({ action: 'stop' }); };
  document.getElementById('music-next').onclick = function () { unlock(); send({ action: 'next' }); };
  shuffleButton.onclick = function () { send({ action: 'shuffle', on: !state.shuffle }); };
  repeatButton.onclick = function () {
    send({ action: 'repeat', mode: state.repeat === 'off' ? 'all' : state.repeat === 'all' ? 'one' : 'off' });
  };
  seekEl.onmousedown = seekEl.ontouchstart = function () { dragging = true; };
  seekEl.onchange = function () {
    dragging = false;
    players[active].currentTime = Number(seekEl.value);
  };
  seekEl.ontouchend = function () { dragging = false; };

  // --- lists ----------------------------------------------------------------------------------------

  // One line of a list: tap the line to open it, tap the button to play it.
  function row(options) {
    var item = node('li', 'row');
    if (options.trackId) item.setAttribute('data-track', String(options.trackId));
    if (options.albumId !== undefined && options.cover) {
      var img = document.createElement('img');
      img.className = 'cover';
      img.alt = '';
      img.src = coverUrl(options.albumId, 96);
      item.appendChild(img);
    }
    var main = node('div', 'main');
    main.appendChild(node('div', 'name', options.title));
    if (options.sub) main.appendChild(node('div', 'sub', options.sub));
    if (options.onOpen) main.onclick = options.onOpen;
    item.appendChild(main);
    if (options.extra) item.appendChild(node('div', 'extra', options.extra));
    if (options.onPlay) {
      var button = node('button', 'go', 'Play');
      button.type = 'button';
      button.onclick = options.onPlay;
      item.appendChild(button);
    }
    return item;
  }

  function section(title) {
    return node('h2', 'section', title);
  }

  function list() {
    return node('ul', 'rows');
  }

  function empty(text) {
    return node('p', 'empty', text);
  }

  function actions(buttons) {
    var wrap = node('div', 'actions');
    for (var i = 0; i < buttons.length; i++) {
      var button = node('button', 'act' + (buttons[i].primary ? ' primary' : ''), buttons[i].label);
      button.type = 'button';
      button.onclick = buttons[i].onClick;
      wrap.appendChild(button);
    }
    return wrap;
  }

  function moreButton(shown, total, onMore) {
    if (shown >= total) return document.createDocumentFragment();
    var button = node('button', 'act', 'Show more');
    button.type = 'button';
    button.onclick = onMore;
    return button;
  }

  function trackRow(track, onPlay, showAlbum) {
    return row({
      title: (track.track_no ? track.track_no + '. ' : '') + track.title,
      sub: track.artist + (showAlbum && track.album ? ' · ' + track.album : ''),
      extra: track.duration_s ? clock(track.duration_s) : '',
      trackId: track.id,
      onOpen: onPlay,
      onPlay: onPlay
    });
  }

  function backBar() {
    var wrap = node('div', 'back');
    if (stack.length) {
      var button = node('button', 'act', 'Back');
      button.type = 'button';
      button.onclick = back;
      wrap.appendChild(button);
    }
    return wrap;
  }

  function fail(code) {
    clear(body);
    body.appendChild(empty(code === 403 ? 'Not allowed from here.' : 'Could not load this. Try again.'));
  }

  // --- the views -----------------------------------------------------------------------------------

  function openView(fn) {
    if (current) stack.push(current);
    current = fn;
    fn();
  }

  function back() {
    current = stack.length ? stack.pop() : null;
    if (current) current();
  }

  function topView(fn) {
    stack = [];
    current = fn;
    searchInput.value = '';
    fn();
  }

  function selectorOf(item) {
    return item.selector;
  }

  function openItem(item) {
    var selector = item.selector;
    if (item.kind === 'album') openView(function () { showAlbum(selector.album_id); });
    else if (item.kind === 'playlist') openView(function () { showPlaylist(selector.playlist_id); });
    else if (item.kind === 'folder') openView(function () { showFolder(selector.source_id, selector.path); });
  }

  function showHome() {
    clear(body);
    request('GET', BASE + '/content', null, function (code, data) {
      if (code !== 200 || !data) { fail(code); return; }
      clear(body);
      var any = false;
      var i;
      var playable = [];
      for (i = 0; i < data.favorites.length; i++) if (data.favorites[i].available) playable.push(data.favorites[i]);
      if (playable.length) {
        any = true;
        body.appendChild(section('Favourites'));
        var favorites = list();
        var ids = [];
        for (i = 0; i < playable.length; i++) ids.push(playable[i].selector.track_id);
        playable.forEach(function (item) {
          favorites.appendChild(row({
            title: item.title || item.name,
            sub: item.title ? item.name : '',
            trackId: item.selector.track_id,
            onOpen: function () { play({ track_ids: ids }, item.selector.track_id); },
            onPlay: function () { play({ track_ids: ids }, item.selector.track_id); }
          }));
        });
        body.appendChild(favorites);
      }
      var suggestions = [];
      for (i = 0; i < data.suggestions.length; i++) if (data.suggestions[i].available) suggestions.push(data.suggestions[i]);
      if (suggestions.length) {
        any = true;
        body.appendChild(section('Suggestions'));
        var offered = list();
        suggestions.forEach(function (item) {
          offered.appendChild(row({
            title: item.title || item.name,
            sub: item.kind === 'album' ? 'Album' : item.kind === 'folder' ? 'Folder' : 'Playlist',
            onOpen: function () { openItem(item); },
            onPlay: function () { play(selectorOf(item)); }
          }));
        });
        body.appendChild(offered);
      }
      var playlists = [];
      for (i = 0; i < data.playlists.length; i++) if (data.playlists[i].playable) playlists.push(data.playlists[i]);
      if (playlists.length) {
        any = true;
        body.appendChild(section('Playlists'));
        var lists = list();
        playlists.forEach(function (playlist) {
          lists.appendChild(row({
            title: playlist.name,
            sub: playlist.playable + ' tracks · ' + minutes(playlist.duration_s),
            onOpen: function () { openView(function () { showPlaylist(playlist.id); }); },
            onPlay: function () { play({ playlist_id: playlist.id }); }
          }));
        });
        body.appendChild(lists);
      }
      if (!any) body.appendChild(empty('Nothing is offered here yet. Look through Albums, Genres or Folders.'));
    });
  }

  function showAlbums(genre) {
    var shown = 0;
    clear(body);
    body.appendChild(backBar());
    if (genre) body.appendChild(section(genre.name === null ? 'No genre' : genre.name));
    var rows = list();
    body.appendChild(rows);
    var more = node('div', 'more');
    body.appendChild(more);
    function loadMore() {
      var params = { limit: PAGE, offset: shown };
      if (genre) {
        if (genre.name === null) params.no_genre = 'true';
        else params.genre = genre.name;
      }
      request('GET', BASE + '/albums?' + query(params), null, function (code, data) {
        if (code !== 200 || !data) { fail(code); return; }
        data.items.forEach(function (album) {
          rows.appendChild(row({
            title: album.title,
            sub: album.artist + (album.year ? ' · ' + album.year : '') + ' · ' + album.tracks + ' tracks',
            albumId: album.id,
            cover: album.has_cover,
            onOpen: function () { openView(function () { showAlbum(album.id); }); },
            onPlay: function () { play({ album_id: album.id }); }
          }));
        });
        shown += data.items.length;
        clear(more);
        if (!shown) rows.appendChild(empty('No albums yet.'));
        more.appendChild(moreButton(shown, data.total, loadMore));
      });
    }
    loadMore();
  }

  function showAlbum(id) {
    clear(body);
    request('GET', BASE + '/albums/' + id, null, function (code, data) {
      if (code !== 200 || !data) { fail(code); return; }
      clear(body);
      body.appendChild(backBar());
      var head = node('div', 'head');
      if (data.album.has_cover) {
        var img = document.createElement('img');
        img.className = 'cover big';
        img.alt = '';
        img.src = coverUrl(id, 300);
        head.appendChild(img);
      }
      var text = node('div', 'headtext');
      text.appendChild(node('h2', 'title', data.album.title));
      text.appendChild(node('div', 'sub', data.album.artist + (data.album.year ? ' · ' + data.album.year : '') + ' · ' + data.album.tracks + ' tracks · ' + minutes(data.album.duration_s)));
      head.appendChild(text);
      body.appendChild(head);
      body.appendChild(actions([
        { label: 'Play album', primary: true, onClick: function () { play({ album_id: id }); } },
        { label: 'Shuffle', onClick: function () { play({ album_id: id }, null, true); } }
      ]));
      var rows = list();
      data.tracks.forEach(function (track) {
        rows.appendChild(trackRow(track, function () { play({ album_id: id }, track.id); }, false));
      });
      body.appendChild(rows);
      markRows();
    });
  }

  function showPlaylist(id) {
    clear(body);
    request('GET', BASE + '/playlists/' + id, null, function (code, data) {
      if (code !== 200 || !data) { fail(code); return; }
      clear(body);
      body.appendChild(backBar());
      body.appendChild(node('h2', 'title', data.playlist.name));
      body.appendChild(node('div', 'sub', data.playlist.playable + ' tracks · ' + minutes(data.playlist.duration_s)));
      body.appendChild(actions([
        { label: 'Play', primary: true, onClick: function () { play({ playlist_id: id }); } },
        { label: 'Shuffle', onClick: function () { play({ playlist_id: id }, null, true); } }
      ]));
      var rows = list();
      data.tracks.forEach(function (track) {
        if (!track.available) return;
        rows.appendChild(trackRow(track, function () { play({ playlist_id: id }, track.id); }, true));
      });
      body.appendChild(rows);
      markRows();
    });
  }

  function showGenres() {
    clear(body);
    request('GET', BASE + '/genres', null, function (code, data) {
      if (code !== 200 || !data) { fail(code); return; }
      clear(body);
      var rows = list();
      data.forEach(function (genre) {
        rows.appendChild(row({
          title: genre.name === null ? 'No genre' : genre.name,
          sub: genre.albums + ' albums · ' + genre.tracks + ' tracks',
          onOpen: function () { openView(function () { showAlbums({ name: genre.name }); }); }
        }));
      });
      body.appendChild(rows);
      if (!data.length) body.appendChild(empty('No music yet.'));
    });
  }

  function showLocations() {
    clear(body);
    request('GET', BASE + '/locations', null, function (code, data) {
      if (code !== 200 || !data) { fail(code); return; }
      clear(body);
      var rows = list();
      data.forEach(function (location) {
        rows.appendChild(row({
          title: location.name,
          sub: location.tracks + ' tracks',
          onOpen: function () { openView(function () { showFolder(location.id, ''); }); },
          onPlay: function () { play({ source_id: location.id, path: '' }); }
        }));
      });
      body.appendChild(rows);
      if (!data.length) body.appendChild(empty('No music yet.'));
    });
  }

  function showFolder(sourceId, path) {
    clear(body);
    request('GET', BASE + '/folders?' + query({ source_id: sourceId, path: path }), null, function (code, data) {
      if (code !== 200 || !data) { fail(code); return; }
      clear(body);
      body.appendChild(backBar());
      body.appendChild(node('h2', 'title', data.path || data.source_name));
      body.appendChild(actions([
        { label: 'Play folder', primary: true, onClick: function () { play({ source_id: sourceId, path: data.path }); } },
        { label: 'Shuffle', onClick: function () { play({ source_id: sourceId, path: data.path }, null, true); } }
      ]));
      var folders = list();
      data.folders.forEach(function (sub) {
        folders.appendChild(row({
          title: sub.name,
          sub: sub.tracks + ' tracks',
          onOpen: function () { openView(function () { showFolder(sourceId, sub.path); }); },
          onPlay: function () { play({ source_id: sourceId, path: sub.path }); }
        }));
      });
      body.appendChild(folders);
      var tracks = list();
      data.tracks.forEach(function (track) {
        tracks.appendChild(trackRow(track, function () { play({ source_id: sourceId, path: data.path }, track.id); }, true));
      });
      body.appendChild(tracks);
      markRows();
    });
  }

  function showSearch(text) {
    var found = [];
    clear(body);
    var info = node('p', 'sub');
    body.appendChild(info);
    var rows = list();
    body.appendChild(rows);
    var more = node('div', 'more');
    body.appendChild(more);
    function loadMore() {
      request('GET', BASE + '/tracks?' + query({ q: text, limit: PAGE, offset: found.length }), null, function (code, data) {
        if (code !== 200 || !data) { fail(code); return; }
        data.items.forEach(function (track) {
          found.push(track);
          rows.appendChild(trackRow(track, function () {
            var ids = [];
            for (var i = 0; i < found.length && i < PLAY_LIST_MAX; i++) ids.push(found[i].id);
            play({ track_ids: ids }, track.id);
          }, true));
        });
        info.textContent = data.total + ' tracks found';
        clear(more);
        more.appendChild(moreButton(found.length, data.total, loadMore));
        markRows();
      });
    }
    loadMore();
  }

  // --- the top buttons and the search box ---------------------------------------------------------------

  var tabs = [
    { id: 'music-home', view: showHome },
    { id: 'music-albums', view: function () { showAlbums(null); } },
    { id: 'music-genres', view: showGenres },
    { id: 'music-folders', view: showLocations }
  ];

  function markTab(activeId) {
    var buttons = nav.getElementsByTagName('button');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].className = 'sub-tab' + (buttons[i].id === activeId ? ' active' : '');
    }
  }

  tabs.forEach(function (tab) {
    document.getElementById(tab.id).onclick = function () {
      markTab(tab.id);
      topView(tab.view);
    };
  });

  searchInput.oninput = function () {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(function () {
      var text = searchInput.value.replace(/^\s+|\s+$/g, '');
      markTab(text ? '' : 'music-home');
      if (text) {
        stack = [];
        current = function () { showSearch(text); };
        current();
      } else {
        topView(showHome);
      }
    }, SEARCH_DELAY_MS);
  };

  // --- going --------------------------------------------------------------------------------------------

  function poll() {
    request('GET', BASE + '/session?client_id=' + encodeURIComponent(sid), null, function (code, data) {
      if (code === 200 && data) apply(data);
    });
  }

  // Opened the first time the Music tab is shown, so a tablet that only plays the radio never asks for it.
  function start() {
    if (started) return;
    started = true;
    request('GET', BASE + '/session?client_id=' + encodeURIComponent(sid), null, function (code, data) {
      if (code === 200 && data) {
        // A reloaded page does not start sound by itself.
        var wasPlaying = data.status === 'playing';
        if (wasPlaying) data.status = 'paused';
        apply(data);
        if (wasPlaying) send({ action: 'pause' });
      }
      window.setInterval(poll, POLL_MS);
    });
    markTab('music-home');
    topView(showHome);
  }

  wirePlayer(0);
  wirePlayer(1);
  say('');
  bar.style.display = 'none';

  window.HomeStartMusic = {
    start: start,
    // Called when the radio starts: only one thing plays at a time.
    pause: function () { if (state.status === 'playing') send({ action: 'pause' }); }
  };
  if (window.HomeStartPanel) window.HomeStartPanel.onRadioStart = window.HomeStartMusic.pause;
}());
