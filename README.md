# INWX for Home Assistant

![Status: Work in Progress](https://img.shields.io/badge/status-WIP-orange)
![AI-generated](https://img.shields.io/badge/code-AI--generated-blueviolet)

> [!WARNING]
> **Work in Progress:** This integration has not been tested with a real INWX account yet.
> Features and entities may still change.

> [!NOTE]
> **AI-generated:** The code, tests and documentation of this project were created with AI
> (Claude Code, Anthropic).

Custom integration that monitors an [INWX](https://www.inwx.de/) account through the
DomRobot API (JSON-RPC): domains, renewal dates, renewal prices and the account balance. A
binary sensor warns when the balance does not cover the upcoming automatic renewals.

Intended mainly for `.de` domains, where WHOIS does not provide an expiration date.

## Installation

### HACS (custom repository)

1. HACS → menu → **Custom repositories** → URL of this repository, type **Integration**.
2. Install **INWX** and restart Home Assistant.

### Manual

Copy the folder `custom_components/inwx` to `<config>/custom_components/inwx` and restart
Home Assistant.

## Setup

**Settings → Devices & services → Add integration → INWX**

| Field | Description |
|-------|-------------|
| Username | Username of the INWX account |
| Password | Password of the INWX account |
| 2FA secret | Base32 key from the INWX 2FA setup. Only required if the account uses two-factor authentication. |

The 2FA secret is the key shown when two-factor authentication is set up (usually as a QR
code, with the text version below it). The integration generates the one-time codes from it
itself. If the key was not saved at the time, 2FA has to be set up again at INWX.

INWX does not offer API keys. The integration therefore logs in with the account credentials
and has the same permissions as the account. It only reads data and does not change anything.

Changed credentials: After a login error, Home Assistant asks for new credentials on its own.
To change them manually, use **Reconfigure** in the integration menu.

## Options

| Option | Default | Description |
|--------|---------|-------------|
| Forecast period | 30 days | Period in which automatic renewals are added up and compared with the available balance (1–365 days). |
| Prices including VAT | on | Use renewal prices including VAT. Turn off if the account is billed net. |

## Entities

### Device "INWX &lt;username&gt;"

| Entity | Type | Description |
|--------|------|-------------|
| Available balance | Sensor (monetary) | Available balance according to INWX (`available`). |
| Renewal costs in forecast period | Sensor (monetary) | Sum of the renewal prices of all automatic renewals up to the end of the forecast period. |
| Next renewal | Sensor (timestamp) | Earliest renewal date of all domains with automatic renewal. |
| Balance for renewals | Binary sensor (problem) | `Problem` if the renewal costs in the forecast period are higher than the available balance. |

### One device per domain

| Entity | Type | Description |
|--------|------|-------------|
| Renewal date | Sensor (timestamp) | Time at which INWX renews the domain (`reDate`). |
| Expiration date | Sensor (timestamp) | End of the paid period (`exDate`). |
| Renewal price | Sensor (monetary) | Renewal price of the domain for its period. |
| Renewal mode | Sensor (enum) | Renew automatically / Delete automatically / Expire automatically. |
| Status | Sensor | Domain status according to INWX. |

New domains get a device automatically on the next update. Domains that leave the account
are removed together with their device.

## Calculation of the balance warning

- Only domains with renewal mode **Renew automatically** are taken into account.
- Every renewal whose date lies before the end of the forecast period is counted. Renewal
  dates in the past (not yet charged) are counted as well.
- Domains with a short period (e.g. `1M`) are counted once per period within the forecast
  period.
- The costs are compared with the available balance. A credit limit is not taken into
  account.

Example: balance €5.00, renewal of domain A in 25 days (€4.76) and of domain B in 29 days
(€4.76). With a forecast period of 30 days, the costs are €9.52 and the binary sensor is
`Problem`.

## Data updates

Once per hour: login, balance, domain list, renewal price per domain, logout. Each 2FA code
is used only once. If two logins happen within the same 30-second window (e.g. right after
setup), the integration waits for the next code.

## Known limitations

- The parsing of the price response (`domain.getalldomainprices`) and the time format of the
  API are derived from the API documentation and have not been checked against a real
  account yet. Timestamps without a time zone are read as German local time.
- The icon in `custom_components/inwx/brand/icon.png` is the INWX logo (globe), created from
  the INWX GitHub profile picture. There is only `icon.png` (256 × 256), because the source
  is too small for a sharp 512 px version. The trademark belongs to INWX.

## Development

```bash
uv venv .venv --python 3.14
uv pip install --python .venv/bin/python -r requirements_test.txt
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
