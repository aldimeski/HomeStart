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

If Škoda asks to accept new terms, open the MyŠkoda app once, accept them and try again.
**Sign out of Škoda account** deletes the stored login and all saved car data.

## Configuration

- **Links** (administrators): add, edit, delete and reorder ShoLink links; choose an icon from the library,
  the device icons or upload your own (SVG, PNG, WebP or ICO up to 256 KB).
- **Users** (administrators): add users, change their role, deactivate them, reset passwords, delete them.
  The last active administrator cannot be removed.
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
