import network
import socket
import ure
import time
import os

ap_ssid = "WifiManager"
ap_password = "tayfunulu"
ap_authmode = 3  # WPA2
connect_to_open_wifis = False

NETWORK_PROFILES = 'wifi.dat'

wlan_ap = network.WLAN(network.AP_IF)
wlan_sta = network.WLAN(network.STA_IF)

server_socket = None


def unquote_plus(s):
    r = s.replace('+', ' ').split('%')
    for i in range(1, len(r)):
        s = r[i]
        try:
            r[i] = chr(int(s[:2], 16)) + s[2:]
        except ValueError:
            r[i] = '%' + s
    return ''.join(r)


def get_connection():
    """return a working WLAN(STA_IF) instance or None"""

    # First check if there already is any connection:
    if wlan_sta.isconnected():
        return wlan_sta

    connected = False
    try:
        # ESP connecting to WiFi takes time, wait a bit and try again:
        time.sleep(3)
        if wlan_sta.isconnected():
            return wlan_sta

        # Read known network profiles from file
        profiles = read_profiles()

        # Search WiFis in range
        wlan_sta.active(True)
        networks = wlan_sta.scan()

        AUTHMODE = {0: "open", 1: "WEP", 2: "WPA-PSK",
                    3: "WPA2-PSK", 4: "WPA/WPA2-PSK"}
        for ssid, bssid, channel, rssi, authmode, hidden in sorted(networks, key=lambda x: x[3], reverse=True):
            ssid = ssid.decode('utf-8')
            encrypted = authmode > 0
            print("ssid: %s chan: %d rssi: %d authmode: %s" %
                  (ssid, channel, rssi, AUTHMODE.get(authmode, '?')))
            if encrypted:
                if ssid in profiles:
                    password = profiles[ssid]
                    connected = do_connect(ssid, password)
                else:
                    print("skipping unknown encrypted network")
            elif connect_to_open_wifis:
                connected = do_connect(ssid, None)
            if connected:
                break

    except OSError as e:
        print("exception", str(e))

    # start web server for connection manager:
    if not connected:
        connected = start()

    return wlan_sta if connected else None


def read_profiles():
    if NETWORK_PROFILES not in os.listdir():
        return {}

    with open(NETWORK_PROFILES) as f:
        lines = f.readlines()
    profiles = {}
    for line in lines:
        ssid, password = line.strip("\n").split(";")
        profiles[ssid] = password
    return profiles


def write_profiles(profiles):
    lines = []
    for ssid, password in profiles.items():
        lines.append("%s;%s\n" % (ssid, password))
    with open(NETWORK_PROFILES, "w") as f:
        f.write(''.join(lines))


def do_connect(ssid, password):
    wlan_sta.active(True)
    if wlan_sta.isconnected():
        return None
    print('Trying to connect to %s...' % ssid)
    wlan_sta.connect(ssid, password)
    for retry in range(100):
        connected = wlan_sta.isconnected()
        if connected:
            break
        time.sleep(0.1)
        print('.', end='')
    if connected:
        print('\nConnected. Network config: ', wlan_sta.ifconfig())
    else:
        wlan_sta.disconnect()  # fixes issue "STA is connecting, scan are not allowed!"
        print('\nFailed. Not Connected to: ' + ssid)
    return connected


def send_header(client, status_code=200, content_length=None):
    client.sendall("HTTP/1.0 {} OK\r\n".format(status_code))
    client.sendall("Content-Type: text/html; charset=UTF-8\r\n")
    if content_length is not None:
        client.sendall("Content-Length: {}\r\n".format(content_length))
    client.sendall("\r\n")


def send_response(client, payload, status_code=200):
    content_length = len(payload)
    send_header(client, status_code, content_length)
    if content_length > 0:
        client.sendall(payload)
    client.close()


def handle_root(client):
    wlan_sta.active(True)
    ssids = sorted(ssid.decode('utf-8') for ssid, *_ in wlan_sta.scan())
    send_header(client)
    client.sendall("""\
        <html><head><style>
            html {
                background-color: #eee;
            }
            body { 
                font-family: sans-serif;
                max-width: 500px;
                margin: 50px auto;
                font-size: 0.8rem;
            }
            #container {
                border: outset silver 1px;
                background-color: white;
                padding: 50px;
                margin: 0 0 50px 0;
                color: #000;
                font-size: 1rem;
            }
            h1 {
                margin-top: 0;
                text-align: center;
            }
            </style></head>
            <body><div id="container">
            <h1>Wi-Fi setup 📶</h1>
            <form action="configure" method="post">""")
    for ssid in ssids:
        client.sendall(
            '<div><label><input type="radio" name="ssid" value="' + ssid + '" />' + ssid + '</label></div>')

    client.sendall("""
                <p>
                    Password:
                    <input name="password" type="password" />
                    <input type="submit" value="Submit" />
                </p>
            </form>
            </div>
            <p>
                Your ssid and password information will be saved into the
                """ + NETWORK_PROFILES + """ file in your ESP module for future usage.
                Be careful about security!
            </p>
            <ul>
                <li>
                    Original code from <a href="https://github.com/cpopp/MicroPythonSamples"
                        target="_blank" rel="noopener">cpopp/MicroPythonSamples</a>.
                </li>
                <li>
                    This code available at <a href="https://github.com/tayfunulu/WiFiManager"
                        target="_blank" rel="noopener">tayfunulu/WiFiManager</a>.
                </li>
            </ul>
        </body></html>
    """)
    client.close()


def handle_configure(client, content):
    match = ure.search("ssid=([^&]*)&password=(.*)", content)

    if match is None:
        send_response(client, "Parameters not found", status_code=400)
        return False
    # version 1.9 compatibility
    try:
        ssid = unquote_plus(match.group(1).decode("utf-8"))
        password = unquote_plus(match.group(2).decode("utf-8"))
    except UnicodeEncodeError:
        ssid = unquote_plus(match.group(1))
        password = unquote_plus(match.group(2))
    if len(ssid) == 0:
        send_response(client, "SSID must be provided", status_code=400)
        return False

    if do_connect(ssid, password):
        response = """\
            <html>
                <center>
                    <br><br>
                    <h1>
                        ESP successfully connected to WiFi network %(ssid)s.
                    </h1>
                    <br><br>
                </center>
            </html>
        """ % dict(ssid=ssid)
        send_response(client, response)
        try:
            profiles = read_profiles()
        except OSError:
            profiles = {}
        profiles[ssid] = password
        write_profiles(profiles)

        time.sleep(5)

        return True
    else:
        response = """\
            <html>
                <center>
                    <br><br>
                    <h1>
                        ESP could not connect to WiFi network %(ssid)s.
                    </h1>
                    <br><br>
                    <form>
                        <input type="button" value="Go back!" onclick="history.back()"></input>
                    </form>
                </center>
            </html>
        """ % dict(ssid=ssid)
        send_response(client, response)
        return False


def handle_not_found(client, url):
    send_response(client, "Path not found: {}".format(url), status_code=404)


def stop():
    global server_socket

    if server_socket:
        server_socket.close()
        server_socket = None


def start(port=80):
    global server_socket

    addr = socket.getaddrinfo('0.0.0.0', port)[0][-1]

    stop()

    wlan_sta.active(True)
    wlan_ap.active(True)

    wlan_ap.config(essid=ap_ssid, password=ap_password, authmode=ap_authmode)

    server_socket = socket.socket()
    server_socket.bind(addr)
    server_socket.listen(1)

    print('Connect to WiFi ssid ' + ap_ssid +
          ', default password: ' + ap_password)
    print('and access the ESP via your favorite web browser at 192.168.4.1.')
    print('Listening on:', addr)

    while True:
        if wlan_sta.isconnected():
            # stop AP mode to save energy
            wlan_ap.active(False)
            return True

        client, addr = server_socket.accept()
        print('client connected from', addr)
        try:
            client.settimeout(5.0)
            request = bytearray()
            try:
                while "\r\n\r\n" not in request:
                    request.extend(client.recv(512))
            except OSError:
                pass

            if "HTTP" not in request:
                # skip invalid requests
                continue

            if "POST" in request and "Content-Length: " in request:
                content_length = int(ure.search(
                    "Content-Length: ([0-9]+)?", bytes(request)).group(1))
                content = bytearray(
                    request[bytes(request).index(b"\r\n\r\n") + 4:])
                content_length_remaining = content_length - len(content)

                while content_length_remaining > 0:
                    chunk = client.recv(512)
                    content.extend(chunk)
                    content_length_remaining -= len(chunk)

            request = bytes(request)

            print("Request is: {}".format(request))

            # version 1.9 compatibility
            try:
                url = ure.search("(?:GET|POST) /(.*?)(?:\\?.*?)? HTTP",
                                 request).group(1).decode("utf-8").rstrip("/")
            except Exception:
                url = ure.search(
                    "(?:GET|POST) /(.*?)(?:\\?.*?)? HTTP", request).group(1).rstrip("/")
            print("URL is {}".format(url))

            if url == "":
                handle_root(client)
            elif url == "configure":
                handle_configure(client, bytes(content))
            else:
                handle_not_found(client, url)

        finally:
            client.close()
