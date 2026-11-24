# HomeStart – user guide

HomeStart is the start page for the home network: links to local applications (ShoLink), the Tasmota and
Zigbee devices (TasmoSiz) and the car (Škoda). It is reachable only inside the home network, at
`http://<server-address>:8000`.

## Signing in

Sign in with your user name and password. After several wrong passwords the account is locked for a few
minutes. You are signed out automatically after a long time without activity, and with **Log out** (the
arrow at the bottom of the menu).

The first administrator account is `admin` / `admin`: change that password right away under
**Configuration → My account**.

There are two roles:

| | User | Administrator |
|---|---|---|
| Open links, see devices and the car | ✓ | ✓ |
| Switch Tasmota relays and Zigbee lights (unless locked) | ✓ | ✓ |
| Read device consoles | ✓ | ✓ |
| Send console commands, lock switches, edit devices, scan the network, Zigbee pairing | | ✓ |
| Manage links and users | | ✓ |

## Menu and appearance

- The menu on the left can be collapsed to icons with **Collapse menu**; hovering an icon shows its name.
  On a phone the menu opens with the ☰ button.
- The sun/moon button at the bottom switches between light and dark. Both choices are remembered for your
  account. Under **My account** you can also pick *Same as system*.

## ShoLink – links

The **ShoLink** group in the menu lists the shared links; click the group name to show or hide them.
A link opens inside HomeStart. Some sites refuse to be shown inside another page; HomeStart then shows
"This page could not be shown here" with **Try again** and **Open in new tab**. Links that should always open in a new tab can be set that way by an
administrator.

## TasmoSiz – devices

The page shows every Tasmota device on the network. Devices are found automatically; new ones appear by
themselves.

Each card shows:

- the device name (and its icon), **Online** / **Offline**, and a lock symbol if its web page needs a login;
- sensor values (temperature, humidity, pressure, power …) and the WiFi signal;
- the **switches**. A switch with an icon shows its state in the icon: a bulb's glass turns yellow, the
  gas boiler's flame orange, other icons turn yellow while on;
- **Web UI** opens the device's own web page in a new tab; **Details** shows address, firmware and more.

Switching waits until the device confirms; if it does not answer, the card shows an error.

**Locked switches.** An administrator can lock a switch with the small padlock next to it. A locked switch
(orange padlock) cannot be switched by anyone in HomeStart until an administrator unlocks it. The button on
the device itself still works.

**Refresh** asks all devices for their current state.

### Consoles

**Console** on a card opens the device's live log next to the device list (below it on a phone). Up to four
consoles can be open at once. Each has buttons to pause, clear the view, turn auto-scroll on or off and
close it. Administrators can type Tasmota commands (e.g. `Status 0`); the arrow keys recall earlier commands.
If a console shows **MQTT only**, the device's web page needs a login that has not been entered yet
(Configuration → Devices); the full log appears once it is set.

### Zigbee

A Zigbee bridge gets its own section below the devices:

- lights with an on/off switch, sensors with their values, remotes and sensors with their battery level;
  link quality (LQI) and the time of the last report for each device. Battery devices sleep between
  reports, so an old "last report" is normal for a remote that has not been used;
- **Map** shows the Zigbee network: the bridge, routers (mains-powered devices that pass messages on) and end
  devices, with the link quality of each connection. Administrators can press **Scan network** for a new map;
- **Join** (administrators) lets new Zigbee devices pair for 60 seconds. Put the new device into pairing mode
  while the countdown runs; it appears in the list once the bridge has added it.

### For administrators

- **Edit device** (pencil): name, group/room, an icon for the device and for each switch, switch names.
  Names set here are only used in HomeStart; the device keeps its own.
- **Scan network** searches the local network for Tasmota devices that are not on MQTT.
- **Add device** adds a device by its address when it is not found automatically.
- **Remove device** hides a device; it comes back if it reports on MQTT again.

## Škoda – the car

Connect your MyŠkoda account once under **Configuration → My account → Škoda account** (the email and
password of the MyŠkoda app). Each HomeStart user connects their own account and sees only their own cars.

The **Škoda** page shows for each car:

- picture, model, licence plate and VIN;
- lock state, mileage, fuel or battery level and range;
- a top view with doors, windows, boot, bonnet and sunroof: green is closed, red is open;
- the parking position on a map, with the address and when the car last reported.

The data is fetched when you open the page for the first time after signing in, when it is older than
15 minutes, and when you press **Refresh**. If Škoda cannot be reached, the last saved data is shown with a
note. HomeStart only reads information; it never locks, unlocks or controls the car.

Sometimes Škoda first wants an answer to a marketing consent question or new terms of use. HomeStart then
shows a message with **Open the Škoda page**: open it, accept or decline the consent (either works) or accept
the terms, and press **Connect account** again. The same questions are in the MyŠkoda app under
Profile → Edit my profile.
**Sign out of Škoda account** deletes the stored login and all saved car data.

## Radiopanel – radio and openHAB

**Radiopanel** (below Škoda) has two tabs. **Radio** lists the stations: press one to listen, **Stop** to end.
The track title appears under the station name when the station sends it. The sound goes on while you open
other pages of HomeStart. **Home** shows openHAB (when the administrator has set its address).

The same panel is available without signing in at `http://<server>:8000/openpanel` from the home network. It is
made for old tablets (iPad with iOS 9): open it in Safari, and add it to the home screen with Share → Add to
Home Screen. At most 3 people can listen at the same time; a fourth gets an error.

Administrators manage the stations under **Configuration → Radio**: name, subtitle, an id (used in the
address), one or more stream addresses (tried in order) and, only if needed, a content type.

## Player – music

*Player* in the menu is the music library. Everything is read from the locations an administrator has added; HomeStart
never changes or deletes music files. 
- **Play** buttons are on every track, album, folder and subfolder. *Play album* and *Play folder* (with everything below
  it) start from the first track; the play button of a track starts there and goes on through the album or folder.
  *Shuffle* plays them in random order, *Add to queue* puts them after what is already queued.
- The **player bar** at the bottom stays while you use other pages: previous, play/pause, stop, next, a position slider
  (click or drag to jump inside a track), shuffle, repeat (all / one), volume and the **queue** (click a track to jump to it,
  *Clear* to empty it). "Previous" restarts a track that has played for more than 3 seconds.
- Tracks follow each other without a pause. Starting the player stops the radio. After a page reload the queue is still there
  but paused. Only a few people can listen at the same time (`max_listeners` in `homestart.ini`).

- **Albums**: all albums, sorted by title, artist or year; open one to see its tracks.
- **Genres**: genres with the number of albums and tracks; open one to see its albums.
- **Folders**: browse like in a file manager – location, folder, subfolder, tracks.
- **Pictures**: albums show their cover (from the music files, from a picture in the folder such as `cover.jpg`, or from
  the Cover Art Archive) in the lists, on the album page and in the player bar. Administrators can ask for a new lookup of
  one album on its page.
- **Playlists** (tab): make your own from any tracks. *Add to playlist* is on every track, album and folder (and *Save as
  playlist* in the queue); inside a playlist you can reorder, remove, rename and delete, and play it, shuffle it or add it
  to the queue. A playlist is private to you. *Panel playlists* are made by an administrator, shown to everybody and
  also offered on the openpanel; others can play but not change them. A track whose file has gone stays on the list, greyed,
  and is skipped.
- **Search** (top right): title, artist or album, without caring about capitals or accents.

### For administrators

*Configuration → Player* lists the music locations. Add a folder of the server (full path, e.g. `/srv/music`) or a
**network share**: choose *Network share (SMB)*, enter the path like `\\192.168.1.20\Music\Albums` (server, share, optional
folder), the user name and the password (empty user name = guest), and press *Test connection* to see whether it works
and how many music files it finds. The password is stored encrypted and never shown again; when you edit the location,
leave the password empty to keep it. Only servers of the local network are allowed. Then *Scan again*. A scan runs in the background; when it is over, *Report* shows what is new, changed or removed
since the last scan, including new and removed folders. Scan again whenever files have been added or deleted.
Files that disappeared stay in the library as "missing" for 30 days; *remove from library* clears them at once.
**Openpanel content.** The openpanel (no login) offers the whole library and, on top, what you choose: *panel playlists*
(tick *A panel playlist* when making one), *favourite tracks* (the star on a track) and *suggestions* (*Offer on the openpanel*
on an album, a folder or a panel playlist). *Configuration → Player → Openpanel content* lists favourites and suggestions
for reordering, retitling and removing.

*Album pictures and details* (further down on the same page) shows how many albums have a picture and lets you switch the online
lookup on or off. With it on, albums are searched on MusicBrainz (year, genre) and the Cover Art Archive (picture) in the background;
only the artist and album names and the number of tracks are sent. Set `musicbrainz_contact` in `homestart.ini`, as MusicBrainz asks
for contact details. *Look up now* and *Try again for those not found* start a lookup at once.

A location that cannot be reached (an unmounted disk, a switched-off NAS, a wrong password) never removes anything. Switching a location off
hides its music from listeners.

### The openpanel – music on a tablet

`/openpanel` (the address of the Radiopanel) has a **Music** tab, with no login, from the networks allowed for the radio.
Every tablet has its own queue. **Home** shows what an administrator offers: *Favourites*, *Suggestions* and the *Playlists*; tap a
line to open it, tap *Play* to play it at once. *Albums*, *Genres* and *Folders* browse the whole library, and the search box
finds tracks by title, artist or album. At the bottom: previous, play/pause, stop, next, shuffle, repeat and a position slider
(touch to jump inside a track). Tracks follow each other without a pause. Only MP3 and M4A/AAC are shown, since an old iPad
cannot play FLAC or OGG (`openpanel_formats` in `homestart.ini`). Starting the radio pauses the music and the other way round.

## Configuration

- **Links** (administrators): add, edit, delete and reorder ShoLink links; choose an icon from the library,
  the device icons or upload your own (SVG, PNG, WebP or ICO up to 256 KB).
- **Users** (administrators): add users, change their role, deactivate them, reset passwords, delete them.
  The last active administrator cannot be removed.
- **Radio** (administrators): the radio stations of the Radiopanel.
- **Devices** (administrators): the shared login of the Tasmota web pages (used for scanning and consoles;
  stored encrypted) and the list of devices.
- **My account**: your password, appearance, menu and your Škoda account.

## When something does not work

| What you see | What to do |
|---|---|
| "The MQTT broker is not connected" on TasmoSiz | The Mosquitto service on the server is down; HomeStart reconnects by itself when it is back. |
| A device is **Offline** | It has no power or no WiFi. It stays in the list; an administrator can remove it. |
| "The device did not confirm the command" | The device did not answer in time; check it and try again. |
| A link shows "This page could not be shown here" | Use **Open in new tab**, or ask an administrator to set the link to open in a new tab. |
| Škoda shows an error above the data | Škoda's servers are not reachable or changed; the last saved data stays visible. |

Administrators find technical details (installation, backups, settings) in the README.
