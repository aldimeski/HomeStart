/* Radio panel for old tablets (Safari on iOS 9): no fetch, Promise, arrow functions, let or const. */
(function () {
  var STATUS_INTERVAL_MS = 10000;
  var player = document.getElementById('player');
  var listEl = document.getElementById('stations');
  var nowStation = document.getElementById('now-station');
  var nowTitle = document.getElementById('now-title');
  var nowStatus = document.getElementById('now-status');
  var stopButton = document.getElementById('stop');
  var tabRadio = document.getElementById('tab-radio');
  var tabHome = document.getElementById('tab-home');
  var viewRadio = document.getElementById('view-radio');
  var viewHome = document.getElementById('view-home');
  var frame = document.getElementById('home-frame');
  var homeStart = '';
  var stations = [];
  var current = null;
  var statusTimer = null;

  function getJson(url, done) {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', url, true);
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var data = null;
      if (xhr.status === 200) {
        try { data = JSON.parse(xhr.responseText); } catch (e) { data = null; }
      }
      done(data);
    };
    xhr.send();
  }

  // The station and track names come from outside, so they are only ever written as text.
  function setText(el, text) {
    el.textContent = text;
  }

  function setStatus(text, isError) {
    setText(nowStatus, text);
    nowStatus.className = isError ? 'error' : '';
  }

  function markPlaying() {
    var buttons = listEl.getElementsByTagName('button');
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].className = 'station' + (current && buttons[i].getAttribute('data-id') === current.id ? ' playing' : '');
    }
  }

  function loadTitle() {
    if (!current) return;
    var playingId = current.id;
    getJson('/openpanel/status', function (data) {
      if (!data || !current || current.id !== playingId) return;
      for (var i = 0; i < data.stations.length; i++) {
        if (data.stations[i].id === playingId) {
          setText(nowTitle, data.stations[i].title || '');
          return;
        }
      }
    });
  }

  function play(station) {
    current = station;
    setText(nowStation, station.name);
    setText(nowTitle, '');
    setStatus('Connecting…', false);
    stopButton.disabled = false;
    markPlaying();
    player.src = '/openpanel/radio/' + encodeURIComponent(station.id);
    player.load();
    var started = player.play();
    if (started && started.catch) started.catch(function () {});
    window.clearInterval(statusTimer);
    statusTimer = window.setInterval(loadTitle, STATUS_INTERVAL_MS);
    window.setTimeout(loadTitle, 3000);
  }

  function stop() {
    current = null;
    window.clearInterval(statusTimer);
    player.pause();
    // Removing the source closes the connection to the server, so the station is released.
    player.removeAttribute('src');
    player.load();
    setText(nowStation, 'Choose a station');
    setText(nowTitle, '');
    setStatus('', false);
    stopButton.disabled = true;
    markPlaying();
  }

  function renderStations() {
    listEl.innerHTML = '';
    if (!stations.length) {
      var empty = document.createElement('li');
      empty.className = 'empty';
      setText(empty, 'No stations are set up yet.');
      listEl.appendChild(empty);
      return;
    }
    stations.forEach(function (station) {
      var item = document.createElement('li');
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'station';
      button.setAttribute('data-id', station.id);
      setText(button, station.name);
      if (station.sub) {
        var sub = document.createElement('span');
        sub.className = 'sub';
        setText(sub, station.sub);
        button.appendChild(sub);
      }
      button.onclick = function () { play(station); };
      item.appendChild(button);
      listEl.appendChild(item);
    });
    markPlaying();
  }

  function showTab(name) {
    var home = name === 'home';
    viewRadio.style.display = home ? 'none' : '';
    viewHome.style.display = home ? '' : 'none';
    tabRadio.className = 'tab' + (home ? '' : ' active');
    tabHome.className = 'tab' + (home ? ' active' : '');
    // Loaded on the first visit, not at start-up.
    if (home && !frame.getAttribute('src')) frame.src = homeStart;
  }

  player.addEventListener('playing', function () { if (current) setStatus('Playing live', false); });
  player.addEventListener('waiting', function () { if (current) setStatus('Buffering…', false); });
  player.addEventListener('error', function () {
    if (!current) return;
    var code = player.error ? player.error.code : 0;
    setStatus('Cannot play this station (error code ' + code + ')', true);
  });

  stopButton.onclick = stop;
  tabRadio.onclick = function () { showTab('radio'); };
  tabHome.onclick = function () { showTab('home'); };
  document.getElementById('home-reload').onclick = function () { frame.src = homeStart; };

  getJson('/openpanel/stations', function (data) {
    if (!data) {
      setText(listEl, 'Could not load the stations.');
      return;
    }
    stations = data.stations;
    renderStations();
    if (data.openhab_enabled) {
      homeStart = data.openhab_start;
      tabHome.style.display = '';
      document.getElementById('home-open').href = homeStart;
    }
  });
}());
