# Assets Directory

This directory contains images and other assets for your visual novel.

## Directory Structure

- `backgrounds/` - Background images for scenes
- `sprites/` - Character sprite images

## Supported Formats

- PNG (recommended for transparency)
- JPG/JPEG
- GIF (for animated sprites)
- WebP
- SVG

## Image Recommendations

### Backgrounds
- Recommended size: 1200x800 or 16:9 aspect ratio
- Format: JPG or PNG

### Character Sprites
- Recommended size: 400x800 (portrait orientation)
- Format: PNG with transparency
- For animated sprites: Use GIF or WebP

## Usage in Code

Use the helper functions to load assets:

```python
from main import background_asset, sprite_asset

# In your story builder:
builder.set_background(background_asset("courtyard.png"), label="Courtyard")

builder.set_characters([
    CharacterDefinition(
        name="Hero",
        image_url=sprite_asset("hero.png"),
        animated=False
    ),
])
```
