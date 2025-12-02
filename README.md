---
title: Reachy Mini Simple Visual Novel
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 4.44.0
pinned: false
app: app.py
python_version: 3.12
---
## Visual Novel Demo
- Install `uv`
- Run `uv run python app.py`.

### Features
- Register characters with sprite URLs or inline SVG data-URIs (see `create_sprite_data_url`).
- Toggle simple idle animation per character (set `animated=True`) or point to GIF/WebP assets for full animation.
- Change backgrounds between scenes.
- Show, hide, and move characters between left/center/right anchors.
- Display narration or speaker dialogue in a speech-bubble overlay anchored to the scene.
- Navigate forward/backward through the story timeline.
- Opt-in webcam overlay per scene: call `builder.set_camera(True|False)` to show or hide the FastRTC stream alongside your story.
- Voice sandbox: record or upload microphone audio, forward it to a placeholder AI companion, and hear a synthetic confirmation tone back.
- Dynamixel control (Web Serial): connect over serial to XL330 servos and send goal positions directly from the browser—no Python SDK needed.
- **Reachy Mini robot control (WebSocket)**: connect to a Reachy Mini robot server and send real-time pose commands for head position, orientation, body yaw, and antennas.
- Per-scene toggles: show/hide camera, voice, motor, and robot controls with `set_camera`, `set_voice`, `set_motors`, and `set_robot`.

#### Customizing sprites
- Replace the SVG data-URIs in `build_sample_story()` with your own URLs (PNG/GIF/WebP).
- For animated sprites, provide an animated GIF/WebP URL and set `animated=True` to also enable the floaty idle motion.
- If you need frame-based animation control, extend `CharacterDefinition` with additional fields (e.g., `animation_frames`) and update `render_scene()` accordingly.

#### Camera widget
- Grant permission when prompted; the browser's default camera is streamed with FastRTC (`WebRTC` component).
- Scenes control whether the webcam appears. If a scene doesn't request it, you'll see a friendly notice instead of the stream.
- Browsers typically require HTTPS (or `http://localhost`) plus user permission before the stream can start; if the feed doesn’t appear, reload after granting access.

#### Voice sandbox
- Scenes decide whether voice capture shows up. Call `builder.set_voice(True|False)` per scene; when disabled, the audio UI hides completely.
- Use the **Voice & Audio Agent** accordion (when visible) to record or upload a clip; hit **Send to voice agent** to hand it to the (placeholder) AI hook.
- The app echoes your recording for playback and emits a synthetic tone to represent an AI voice. Replace `process_voice_interaction()` in `main.py` with real ASR/LLM/TTS calls to integrate your model stack.
- Default prompt text gives the agent scene context; edit it freely.

#### Dynamixel XL330 control
- The control panel lives entirely in the browser using the Web Serial API (Chrome/Edge on desktop). When prompted, select the USB/serial adapter attached to your Dynamixel bus.
- Choose baud, motor ID, and goal angle in the **Dynamixel XL330 Control** panel; click **Connect serial** (triggers the browser port picker) then **Send goal**. Use **Torque on/off** to toggle torque.
- Commands write Protocol 2.0 registers: torque enable (64) and goal position (116, 4 bytes). Angles 0–360° map to 0–4095 ticks.
- Frontend code lives in `web/dxl_webserial.js` and is loaded via `file=web/dxl_webserial.js`, mirroring the structure of `feetech.js`.

#### Reachy Mini robot control
- Connect to a Reachy Mini robot via WebSocket for real-time pose control during story scenes.
- **Requirements**: A running Reachy Mini server at `localhost:8000` with WebSocket endpoint `/api/move/ws/set_target`.
- The connection status is shown in the robot control panel with a color-coded indicator (🔴 disconnected / 🟢 connected).
- **Enable in scenes**: Call `builder.set_robot(True)` to show the robot control widget for specific scenes.
- **Send poses from story**: Use `builder.send_robot_pose()` to command the robot when a scene is displayed:
  ```python
  builder.send_robot_pose(
      head_x=0.0, head_y=0.0, head_z=0.02,  # Head position in meters
      head_roll=0.0, head_pitch=-0.1, head_yaw=0.0,  # Head orientation in radians
      body_yaw=0.0,  # Body rotation in radians
      antenna_left=-0.2, antenna_right=0.2  # Antenna positions in radians
  )
  ```
- WebSocket automatically connects when the widget becomes visible and reconnects if disconnected.
- Poses are sent automatically when navigating to scenes with robot commands (similar to motor commands and audio).

Edit `main.py` to customize `build_sample_story()` or create your own builder logic with `VisualNovelBuilder`.

### Using Custom Assets

Place your files in the `assets/` directory:
- `assets/backgrounds/` - Background images (1200x800 recommended)
- `assets/sprites/` - Character sprites (400x800 recommended, PNG with transparency)
- `assets/audio/` - Audio files (WAV, MP3, etc.)

Then use the helper functions in your story:

```python
from engine import background_asset, sprite_asset, audio_asset

builder.set_background(background_asset("my_background.png"), label="My Scene")

builder.set_characters([
    CharacterDefinition(
        name="Hero",
        image_url=sprite_asset("hero.png"),
        animated=False
    ),
])

# Play audio when scene is displayed
builder.play_sound(audio_asset("my_sound.wav"))
```
