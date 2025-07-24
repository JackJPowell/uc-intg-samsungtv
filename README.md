# Samsung TV integration for Remote Two/3

This integration is based on the great [samsungtvws](https://github.com/xchwarze/samsung-tv-ws-api) library and uses our
[uc-integration-api](https://github.com/aitatoi/integration-python-library) to communicate with the Remote Two/3.

A [media player entity](https://github.com/unfoldedcircle/core-api/blob/main/doc/entities/entity_media_player.md)
is exposed to the Remote Two/3. A [Remote](https://github.com/unfoldedcircle/core-api/blob/main/doc/entities/entity_remote.md) is also created.

Supported versions:
- Samsung TVs running Tizen OS. If your model is 2017 or newer, you should be good. 

Supported attributes:
- State (on, off, unknown)
- Source List

Supported commands:
- Turn on & off (device will be put into standby)
- Volume up / down
- Mute toggle
- Directional pad navigation and select
- Context menu
- Standard Key Commands
- Launch application

Remote Commands:
- `on`
- `off`
- `toggle`
- `play_pause`
- `volume`
- `volume_up`
- `volume_down`
- `mute_toggle`
- `mute`
- `unmute`
- `channel_up`
- `channel_down`
- `cursor_up`
- `cursor_down`
- `cursor_left`
- `cursor_right`
- `cursor_enter`
- `digit_0`
- `digit_1`
- `digit_2`
- `digit_3`
- `digit_4`
- `digit_5`
- `digit_6`
- `digit_7`
- `digit_8`
- `digit_9`
- `home`
- `menu`
- `context_menu`
- `guide`
- `info`
- `back`
- `select_source`
- `settings`
- `function_red`
- `function_green`
- `function_yellow`
- `function_blue`
- `Channel List`
- `Exit`
- `Sleep`
- `Standby`

### Network

- The Samsung TV device must be on the same network subnet as the Remote. 
- When using DHCP: a static IP address reservation for the Samsung TV device(s) is recommended.
- SDDP discovery is used to detect your Samsung TV on the network.
  - This functionality may need to be manually enabled on your TV.
  - Settings / General / Network / Expert Settings / IP Remote (Enabled)

### Samsung TV device

- A samsung TV that is network enabled and running a version of Tizen OS is required to use the integration. Please refer to the samsungtvws library for additional information on supported models. 

### Launching apps

- For some devices a full list of applications may not be available. By using the send_command option and adding APP_<app_id> you can invoke the application, i.e. to launch Youtube use APP_111299001912. A list of known app_ids to try are available [here](https://github.com/tavicu/homebridge-samsung-tizen/issues/26#issuecomment-447424879)

## Usage

### Docker
```
docker run -d \
  --name Samsung \
  --network host \
  -v $(pwd)/<local_directory>:/config \
  --restart unless-stopped \
  ghcr.io/jackjpowell/uc-intg-samsungtv:latest
```

### Docker Compose

```
  samsungtv:
    container_name: Samsung
    image: ghcr.io/jackjpowell/uc-intg-samsungtv:latest
    network_mode: host
    volumes:
      - ./<local_directory>:/config
    environment:
      - UC_INTEGRATION_HTTP_PORT=9090
    restart: unless-stopped
```

### Install on Remote

- Download tar.gz file from Releases section of this repository
- Upload the file to the remove via the integrations tab (Requires Remote Beta)

### Setup (For Development)

- Requires Python 3.11
- Install required libraries:  
  (using a [virtual environment](https://docs.python.org/3/library/venv.html) is highly recommended)
```shell
pip3 install -r requirements.txt
```

For running a separate integration driver on your network for Remote Two/3, the configuration in file
[driver.json](driver.json) needs to be changed:

- Change `name` to easily identify the driver for discovery & setup  with Remote Two/3 or the web-configurator.
- Optionally add a `"port": 8090` field for the WebSocket server listening port.
    - Default port: `9090`
    - This is also overrideable with environment variable `UC_INTEGRATION_HTTP_PORT`

### Run

```shell
UC_CONFIG_HOME=./ python3 intg-samsungtv/driver.py
```

See available [environment variables](https://github.com/unfoldedcircle/integration-python-library#environment-variables)
in the Python integration library to control certain runtime features like listening interface and configuration directory.

The configuration file is loaded & saved from the path specified in the environment variable `UC_CONFIG_HOME`.
Otherwise, the `HOME` path is used or the working directory as fallback.

The client name prefix used for pairing can be set in ENV variable `UC_CLIENT_NAME`. The hostname is used by default.

## Versioning

We use [SemVer](http://semver.org/) for versioning. For the versions available, see the
[tags and releases in this repository](https://github.com/jackjpowell/uc-intg-samsung-tv/releases).

## Changelog

The major changes found in each new release are listed in the [changelog](CHANGELOG.md)
and under the GitHub [releases](https://github.com/jackjpowell/uc-intg-samsung-tv/releases).

## Contributions

Please read the [contribution guidelines](CONTRIBUTING.md) before opening a pull request.

## License

This project is licensed under the [**Mozilla Public License 2.0**](https://choosealicense.com/licenses/mpl-2.0/).
See the [LICENSE](LICENSE) file for details.
