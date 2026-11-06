# ImmichHomeAssistant

A Home Assistant custom integration that shows rotating photos from your
[Immich](https://immich.app) server: your favorites and selected albums. Ideal for dashboards and digital photo frames.

## Features

* **Image entities** for favorites and every selected album.
  Each source also gets an *original* entity that loads the full-resolution
  photo only when you open it (HEIC/RAW photos are converted by Immich).
* **Controls**: a *next image* button per source, switches for shuffle mode
  and random speed, and a number entity for the refresh interval. Changes
  made with these controls are saved and survive a restart.
* **Tag filter**: only show photos with at least one of the given tags
  (filtered server-side by Immich).
* **No-repeat window**: the last *n* photos are not shown again.
* **Rich attributes** for captions: `photo_date`, `city`, `state`, `country`,
  `description`, `people` and `file_name`.
* Actions (services) for automations: `next_image`, `set_shuffle_mode`,
  `set_random_speed`, `set_refresh_interval`.
* Diagnostics download (API key redacted) and Dutch and English translations.

## Installation

1. In HACS, add `https://github.com/1mfaasj/ImmichHomeAssistant` as a custom
   repository (category *Integration*) and install it.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → ImmichHomeAssistant**.
4. Enter the Immich URL (for example `http://192.168.1.10:2283`) and an API key.
   Create the key in Immich under **Account settings → API keys**. It needs
   read access to assets, albums and tags.

Only one Immich server can be configured.

## Options

| Option | Description |
| --- | --- |
| Albums | Albums for which image entities are created |
| Refresh interval | Seconds between images (10–3600) |
| No-repeat window | Number of recent images that are not repeated |
| Tag filter | Comma-separated tag names |
| Shuffle mode | Show every photo once before repeating |
| Random speed | Vary the interval between 50 % and 150 % |

The `set_*` actions change a setting **temporarily** for the selected image
entities. To change a setting permanently, use the switch/number entities or
the options dialog.

## Entities

Entity IDs depend on your Home Assistant language. With Dutch, for example:

| Entity | Purpose |
| --- | --- |
| `image.immich_favorieten` | Rotating favorite (preview size, ~1440 px) |
| `image.immich_favorieten_origineel` | Full resolution of the current favorite |
| `image.immich_<album>` | Rotating photo from an album |
| `button.immich_favorieten_volgende_foto` | Skip to the next favorite |
| `switch.immich_shufflemodus` | Shuffle mode for all sources |
| `number.immich_verversingsinterval` | Refresh interval for all sources |

Check **Settings → Devices & services → ImmichHomeAssistant → Immich** for the
exact IDs on your system.

## Example dashboard card

This example uses [button-card](https://github.com/custom-cards/button-card).
It shows the current favorite with its date. Tapping opens the full-resolution
photo; holding skips to the next photo. Replace the entity IDs with your own.

```yaml
type: grid
title: Immich favoriete foto's
columns: 2
square: true
cards:
  - type: custom:button-card
    entity: image.immich_favorite
    show_name: false
    show_state: false
    show_entity_picture: true
    tap_action:
      action: more-info
      entity: image.immich_favorieten_origineel
    hold_action:
      action: call-service
      service: button.press
      target:
        entity_id: button.immich_favorieten_volgende_foto
    aspect_ratio: null
    styles:
      card:
        - padding: 0
        - overflow: hidden
        - cursor: pointer
      grid:
        - grid-template-areas: '"i" "date"'
        - grid-template-columns: 1fr
        - grid-template-rows: 1fr auto
      img_cell:
        - width: 100%
        - height: 100%
        - justify-self: center
        - align-self: center
      icon:
        - width: 100%
        - height: 100%
      custom_fields:
        date:
          - padding: 8px
          - font-size: 14px
          - text-align: center
    custom_fields:
      date: |
        [[[
          const value = entity.attributes.photo_date;

          if (!value) {
            return 'Geen datum beschikbaar';
          }

          const date = new Date(value);
          const text = date.toLocaleString('nl-NL', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
          });

          const place = entity.attributes.city || entity.attributes.country;
          return place ? `${text} · ${place}` : text;
        ]]]
```

## Development

```bash
pip install -r requirements_test.txt
pytest
```

GitHub Actions runs hassfest, the HACS validation and the tests on every push.

## License

MIT, see [LICENSE](LICENSE).
