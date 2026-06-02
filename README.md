# 📸 ImmichHomeAssistant

![GitHub release](https://img.shields.io/github/v/release/1mfaasj/ImmichHomeAssistant)
![HA validation](https://github.com/1mfaasj/ImmichHomeAssistant/actions/workflows/validate.yml/badge.svg)
![HACS](https://img.shields.io/badge/HACS-Custom-orange)

A Home Assistant custom integration to display random photos from your Immich server.

## ✨ Features

- Random images from Favorites
- Random images from selected albums
- Configurable refresh interval
- No-repeat window to avoid duplicates
- Optional tag filtering (comma-separated)
- Optional shuffle mode
- Optional random slideshow speed around the configured base interval
- Fully configurable through the Home Assistant UI
- Efficient asset list caching to reduce API calls

## 📦 Installation

Install via HACS as a custom repository.

Repository URL:

`https://github.com/1mfaasj/ImmichHomeAssistant`

Restart Home Assistant after installation.

## ⚙️ Configuration

Add the integration from **Settings → Devices & Services → Add Integration**.

Search for: **ImmichHomeAssistant**

You need:

- Immich server URL
- API key from Immich account settings

## 🎛 Options

| Option | Description |
|--------|-------------|
| Watched albums | Select albums to expose as image entities |
| Refresh interval | Base interval between image changes |
| No-repeat window | Avoid recently shown images |
| Tags | Comma-separated tag filter |
| Shuffle mode | Shuffle eligible assets before showing them |
| Random speed | Vary slideshow speed around the base interval |

## 🖼 Example dashboard

```yaml
type: panel
title: Photo frame
path: photo-frame
icon: mdi:image-frame
subview: true
cards:
  - type: picture-entity
    entity: image.immichhomeassistant_favorite_image
    show_state: false
    show_name: false
    aspect_ratio: "16:9"
    fit_mode: contain
```
