"""Visual Novel Gradio App - Main application with UI and handlers."""

from __future__ import annotations

import os
import urllib.parse
import numpy as np
import logging
from typing import Optional

import gradio as gr
from fastrtc import WebRTC

from engine import SceneState, POSITION_OFFSETS, Choice, InputRequest
from story import build_sample_story

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def passthrough_stream(frame):
    """Return the incoming frame untouched so the user sees their feed."""
    return frame


def camera_hint_text(show_camera: bool) -> str:
    if show_camera:
        return "🎥 Webcam overlay is active for this scene."
    return "🕹️ Webcam is hidden for this scene."


def voice_hint_text(show_voice: bool) -> str:
    if show_voice:
        return "🎤 Voice capture is available in this scene."
    return "🔇 Voice capture is hidden for this scene."


def motor_hint_text(show_motors: bool) -> str:
    if show_motors:
        return "🤖 Motor control is available in this scene."
    return "🛑 Motor control hidden for this scene."


def robot_hint_text(show_robot: bool) -> str:
    if show_robot:
        return "🤖 Robot control is available in this scene."
    return "🔒 Robot control hidden for this scene."


# Dynamixel control functions using Python protocol implementation
def dxl_build_ping_packet(motor_id: int) -> list[int]:
    """Build a ping packet and return as list of bytes."""
    import dynamixel
    packet = dynamixel.ping_packet(motor_id)
    return list(packet)


def dxl_build_torque_packet(motor_id: int, enable: bool) -> list[int]:
    """Build a torque enable/disable packet and return as list of bytes."""
    import dynamixel
    packet = dynamixel.torque_enable_packet(motor_id, enable)
    return list(packet)


def dxl_build_goal_position_packet(motor_id: int, degrees: float) -> list[int]:
    """Build a goal position packet and return as list of bytes."""
    import dynamixel
    # Convert degrees to ticks (0-360° -> 0-4095)
    clamped_deg = max(0.0, min(360.0, degrees))
    ticks = int((clamped_deg / 360.0) * 4095)
    packet = dynamixel.goal_position_packet(motor_id, ticks)
    return list(packet)


def dxl_parse_response(response_bytes: list[int]) -> str:
    """Parse a status packet response and return human-readable result."""
    import dynamixel
    if not response_bytes:
        return "❌ No response received"
    success, message = dynamixel.parse_status_packet(bytes(response_bytes))
    if success:
        return f"✅ {message}"
    else:
        return f"❌ {message}"


def get_scene_motor_packets(story_state: dict) -> list:
    """Extract motor commands from current scene and build packets."""
    scenes = story_state["scenes"]
    current_index = story_state["index"]
    if 0 <= current_index < len(scenes):
        scene = scenes[current_index]
        # Build packet for each motor command
        packets = []
        for cmd in scene.motor_commands:
            packet = dxl_build_goal_position_packet(cmd.motor_id, cmd.position)
            packets.append(packet)
        return packets
    return []


def get_scene_audio(story_state: dict) -> Optional[str]:
    """Extract audio file from current scene."""
    scenes = story_state["scenes"]
    current_index = story_state["index"]
    if 0 <= current_index < len(scenes):
        scene = scenes[current_index]
        return scene.audio_file
    return None


def get_scene_robot_pose(story_state: dict) -> Optional[dict]:
    """Extract robot pose from current scene."""
    scenes = story_state["scenes"]
    current_index = story_state["index"]
    if 0 <= current_index < len(scenes):
        scene = scenes[current_index]
        if scene.robot_pose:
            return {
                "target_head_pose": {
                    "x": scene.robot_pose.head_x,
                    "y": scene.robot_pose.head_y,
                    "z": scene.robot_pose.head_z,
                    "roll": scene.robot_pose.head_roll,
                    "pitch": scene.robot_pose.head_pitch,
                    "yaw": scene.robot_pose.head_yaw,
                },
                "target_body_yaw": scene.robot_pose.body_yaw,
                "target_antennas": [scene.robot_pose.antenna_left, scene.robot_pose.antenna_right],
            }
    return None


def synthesize_tone(sample_rate: int = 16000, duration: float = 1.25) -> tuple[int, np.ndarray]:
    """Generate a short confirmation tone to play back as the AI voice."""
    samples = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    carrier = np.sin(2 * np.pi * 520 * samples) + 0.4 * np.sin(2 * np.pi * 880 * samples)
    fade_len = int(sample_rate * 0.08)
    envelope = np.ones_like(carrier)
    envelope[:fade_len] *= np.linspace(0.0, 1.0, fade_len)
    envelope[-fade_len:] *= np.linspace(1.0, 0.0, fade_len)
    tone = 0.18 * carrier * envelope
    return sample_rate, tone.astype(np.float32)


def describe_audio_clip(audio: Optional[tuple[int, np.ndarray]]) -> str:
    if audio is None:
        return "No audio captured yet. Hit record to speak with the companion."
    sample_rate, samples = audio
    num_samples = len(samples) if samples is not None else 0
    if num_samples == 0:
        return "Audio appears empty. Please re-record."
    duration = num_samples / float(sample_rate or 1)
    rms = float(np.sqrt(np.mean(np.square(samples))))
    return f"Captured {duration:.2f}s of audio (RMS ~{rms:.3f}). Ready for the AI."


def process_voice_interaction(
    audio: Optional[tuple[int, np.ndarray]], prompt: str
) -> tuple[str, Optional[tuple[int, np.ndarray]], str, tuple[int, np.ndarray]]:
    summary = describe_audio_clip(audio)
    user_prompt = (prompt or "React to the current scene.").strip()
    if audio is None:
        ai_line = (
            "AI response pending: record or upload an audio clip so the agent can react."
        )
        response_audio = synthesize_tone()
        return summary, None, ai_line, response_audio
    ai_line = (
        "Imaginary AI companion: I'm using your latest microphone input "
        f"and the prompt \"{user_prompt}\" to craft a response."
    )
    response_audio = synthesize_tone()
    return summary, audio, ai_line, response_audio


def render_scene(
    scene: SceneState, index: int, total: int, variables: dict
) -> tuple[str, str, str, bool, bool, bool, bool, Optional[List[Choice]], Optional[InputRequest]]:
    """Generate the HTML stage, dialogue text, and metadata."""
    char_layers = []
    for sprite in scene.characters.values():
        if not sprite.visible:
            continue
        offset = POSITION_OFFSETS.get(sprite.position, "50%")
        # Build class names with animation
        class_names = "character"
        if sprite.animation:
            class_names += f" anim-{sprite.animation}"
        # Apply scale using CSS variable (so animations can use it)
        char_layers.append(
            f"""
            <div class="{class_names}" style="
                left:{offset};
                background-image:url('{sprite.image_url}');
                --char-scale:{sprite.scale};
            " title="{sprite.name}"></div>
            """
        )
    dialogue_markdown = (
        "" if scene.text else ""
    )  # Avoid duplicating the speech bubble content below the stage.
    metadata = f"{scene.background_label or 'Scene'} · {index + 1} / {total}"
    bubble_html = ""
    text_content = (scene.text or "").strip()

    # Substitute variables in text (e.g., {player_name})
    for var_name, var_value in variables.items():
        text_content = text_content.replace(f"{{{var_name}}}", str(var_value))

    if text_content:
        speaker_html = (
            f'<div class="bubble-speaker">{scene.speaker}</div>'
            if scene.speaker
            else ""
        )
        bubble_html = f"""
            <div class="speech-bubble">
                {speaker_html}
                <div class="bubble-text">{text_content}</div>
            </div>
        """
    # Apply blur filters to background and stage
    bg_blur_style = f"filter: blur({scene.background_blur}px);" if scene.background_blur > 0 else ""
    stage_blur_style = f"filter: blur({scene.stage_blur}px);" if scene.stage_blur > 0 else ""

    # Build stage layer HTML if stage image is set
    stage_layer_html = ""
    if scene.stage_url:
        stage_layer_html = f'<div class="stage-layer" style="background-image:url(\'{scene.stage_url}\'); {stage_blur_style}"></div>'

    stage_html = f"""
        <div class="stage">
            <div class="stage-background" style="background-image:url('{scene.background_url}'); {bg_blur_style}"></div>
            {stage_layer_html}
            {''.join(char_layers)}
            {bubble_html}
        </div>
    """
    return (
        stage_html,
        dialogue_markdown,
        metadata,
        scene.show_camera,
        scene.show_voice,
        scene.show_motors,
        scene.show_robot,
        scene.choices,
        scene.input_request,
    )


def is_scene_accessible(scene: SceneState, active_paths: set) -> bool:
    """Check if a scene is accessible given the active story paths."""
    # Scenes with no path are always accessible (main path)
    if scene.path is None:
        return True
    # Scenes with a specific path are only accessible if that path is active
    return scene.path in active_paths


def change_scene(
    story_state: dict, direction: int
) -> tuple[dict, str, str, str, str, dict, str, dict, str, dict, str, dict, dict, str, dict, dict, dict, dict, dict]:
    scenes: List[SceneState] = story_state["scenes"]
    variables = story_state.get("variables", {})
    active_paths = story_state.get("active_paths", set())

    if not scenes:
        return (
            story_state,
            "",
            "No scenes available.",
            "",
            camera_hint_text(False),
            gr.update(visible=False),
            voice_hint_text(False),
            gr.update(visible=False),
            motor_hint_text(False),
            gr.update(visible=False),
            robot_hint_text(False),
            gr.update(visible=False),
            gr.update(visible=False, choices=[]),
            "",  # input_prompt (string, not dict)
            gr.update(visible=False),  # input_group
            gr.update(value=""),  # user_input - clear it
            gr.update(interactive=True),  # prev_btn
            gr.update(interactive=True),  # next_btn
            gr.update(visible=False),  # right_column
        )

    total = len(scenes)
    current_index = story_state["index"]

    # Find the next accessible scene in the given direction
    new_index = current_index
    search_index = current_index + direction

    while 0 <= search_index < total:
        if is_scene_accessible(scenes[search_index], active_paths):
            new_index = search_index
            break
        search_index += direction

    story_state["index"] = new_index
    html, dialogue, meta, show_camera, show_voice, show_motors, show_robot, choices, input_req = render_scene(
        scenes[story_state["index"]], story_state["index"], total, variables
    )

    # Disable navigation when choices or input are present
    nav_enabled = not bool(choices) and not bool(input_req)

    # Show right column if any feature is active
    right_column_visible = show_camera or show_voice or show_motors or show_robot

    return (
        story_state,
        html,
        dialogue,
        meta,
        camera_hint_text(show_camera),
        gr.update(visible=show_camera),
        voice_hint_text(show_voice),
        gr.update(visible=show_voice),
        motor_hint_text(show_motors),
        gr.update(visible=show_motors),
        robot_hint_text(show_robot),
        gr.update(visible=show_robot),
        gr.update(visible=bool(choices), choices=[(c.text, i) for i, c in enumerate(choices)] if choices else [], value=None),
        f"### {input_req.prompt}" if input_req else "",
        gr.update(visible=bool(input_req)),
        gr.update(value=""),  # user_input - clear it
        gr.update(interactive=nav_enabled),
        gr.update(interactive=nav_enabled),
        gr.update(visible=right_column_visible),  # right_column
    )


def handle_choice(story_state: dict, choice_index: int) -> tuple[dict, str, str, str, str, dict, str, dict, str, dict, str, dict, dict, str, dict, dict, dict, dict, dict]:
    """Navigate to the scene selected by the choice."""
    scenes: List[SceneState] = story_state["scenes"]
    variables = story_state.get("variables", {})
    active_paths = story_state.get("active_paths", set())
    current_scene = scenes[story_state["index"]]

    if current_scene.choices and 0 <= choice_index < len(current_scene.choices):
        chosen = current_scene.choices[choice_index]
        story_state["index"] = chosen.next_scene_index

        # Activate the path of the chosen scene
        target_scene = scenes[chosen.next_scene_index]
        if target_scene.path:
            active_paths = set(active_paths)  # Copy the set
            active_paths.add(target_scene.path)
            story_state["active_paths"] = active_paths

        html, dialogue, meta, show_camera, show_voice, show_motors, show_robot, choices, input_req = render_scene(
            scenes[story_state["index"]], story_state["index"], len(scenes), variables
        )

        nav_enabled = not bool(choices) and not bool(input_req)
        right_column_visible = show_camera or show_voice or show_motors or show_robot

        return (
            story_state,
            html,
            dialogue,
            meta,
            camera_hint_text(show_camera),
            gr.update(visible=show_camera),
            voice_hint_text(show_voice),
            gr.update(visible=show_voice),
            motor_hint_text(show_motors),
            gr.update(visible=show_motors),
            robot_hint_text(show_robot),
            gr.update(visible=show_robot),
            gr.update(visible=bool(choices), choices=[(c.text, i) for i, c in enumerate(choices)] if choices else [], value=None),
            f"### {input_req.prompt}" if input_req else "",
            gr.update(visible=bool(input_req)),
            gr.update(value=""),  # user_input - clear it
            gr.update(interactive=nav_enabled),
            gr.update(interactive=nav_enabled),
            gr.update(visible=right_column_visible),  # right_column
        )
    return change_scene(story_state, 0)


def handle_input(story_state: dict, user_input: str) -> tuple[dict, str, str, str, str, dict, str, dict, str, dict, str, dict, dict, str, dict, dict, dict, dict, dict]:
    """Store user input and advance to next scene."""
    logger.info(f"Handling input: {user_input}")
    scenes: List[SceneState] = story_state["scenes"]
    variables = story_state.get("variables", {})
    current_scene = scenes[story_state["index"]]

    if current_scene.input_request and user_input:
        variables[current_scene.input_request.variable_name] = user_input
        story_state["variables"] = variables
        logger.info(f"Stored variable: {current_scene.input_request.variable_name}={user_input}")

    # Advance to next scene
    story_state["index"] = min(story_state["index"] + 1, len(scenes) - 1)
    logger.info(f"Advanced to scene {story_state['index']}")

    html, dialogue, meta, show_camera, show_voice, show_motors, show_robot, choices, input_req = render_scene(
        scenes[story_state["index"]], story_state["index"], len(scenes), variables
    )

    nav_enabled = not bool(choices) and not bool(input_req)
    right_column_visible = show_camera or show_voice or show_motors or show_robot

    logger.info(f"After input: input_req visible={bool(input_req)}, choices visible={bool(choices)}")

    return (
        story_state,
        html,
        dialogue,
        meta,
        camera_hint_text(show_camera),
        gr.update(visible=show_camera),
        voice_hint_text(show_voice),
        gr.update(visible=show_voice),
        motor_hint_text(show_motors),
        gr.update(visible=show_motors),
        robot_hint_text(show_robot),
        gr.update(visible=show_robot),
        gr.update(visible=bool(choices), choices=[(c.text, i) for i, c in enumerate(choices)] if choices else [], value=None),
        f"### {input_req.prompt}" if input_req else "",
        gr.update(visible=bool(input_req)),
        gr.update(value=""),  # user_input - CRITICAL: clear it to prevent duplicate submissions
        gr.update(interactive=nav_enabled),
        gr.update(interactive=nav_enabled),
        gr.update(visible=right_column_visible),  # right_column
    )


def load_initial_state() -> tuple[dict, str, str, str, str, dict, str, dict, str, dict, str, dict, dict, str, dict, dict, dict, dict, dict]:
    logger.info("Loading initial state...")
    scenes = build_sample_story()
    story_state = {"scenes": scenes, "index": 0, "variables": {}, "active_paths": set()}
    if scenes:
        html, dialogue, meta, show_camera, show_voice, show_motors, show_robot, choices, input_req = render_scene(
            scenes[0], 0, len(scenes), {}
        )
        logger.info(f"Initial scene: choices={choices is not None}, input_req={input_req is not None}")
        logger.info(f"HTML length: {len(html) if html else 0}")
    else:
        html, dialogue, meta, show_camera, show_voice, show_motors, show_robot, choices, input_req = (
            "",
            "No scenes available.",
            "",
            False,
            False,
            False,
            False,
            None,
            None,
        )

    nav_enabled = not bool(choices) and not bool(input_req)
    right_column_visible = show_camera or show_voice or show_motors or show_robot

    logger.info(f"Initial state: input_req visible={bool(input_req)}, choices visible={bool(choices)}")

    return (
        story_state,
        html,
        dialogue,
        meta,
        camera_hint_text(show_camera),
        gr.update(visible=show_camera),
        voice_hint_text(show_voice),
        gr.update(visible=show_voice),
        motor_hint_text(show_motors),
        gr.update(visible=show_motors),
        robot_hint_text(show_robot),
        gr.update(visible=show_robot),
        gr.update(visible=bool(choices), choices=[(c.text, i) for i, c in enumerate(choices)] if choices else [], value=None),
        f"### {input_req.prompt}" if input_req else "",
        gr.update(visible=bool(input_req)),
        gr.update(value=""),  # user_input - clear it
        gr.update(interactive=nav_enabled),
        gr.update(interactive=nav_enabled),
        gr.update(visible=right_column_visible),  # right_column
    )


CUSTOM_CSS = """
/* Override Gradio's height constraints for stage container */
#stage-container {
    height: auto !important;
    max-height: none !important;
}
#stage-container > div {
    height: auto !important;
}
.stage {
    width: 100%;
    height: 80vh;
    min-height: 600px;
    border-radius: 0;
    position: relative;
    overflow: hidden;
    box-shadow: 0 12px 32px rgba(15,23,42,0.45);
    display: flex;
    align-items: flex-end;
    justify-content: center;
}
/* Ensure background layers fill the stage */
.stage-background,
.stage-layer {
    max-height: none !important;
}
.stage-background {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-size: contain;
    background-position: center;
    background-repeat: no-repeat;
    z-index: 0;
}
.stage-layer {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-size: contain;
    background-position: center;
    background-repeat: no-repeat;
    z-index: 5;
}
.character {
    position: absolute;
    bottom: 0;
    width: 200px;
    height: 380px;
    background-size: contain;
    background-repeat: no-repeat;
    --char-scale: 1.0;
    transform: translateX(-50%) scale(var(--char-scale));
    transition: transform 0.4s ease;
    z-index: 10;
}
/* Character animations */
.character.anim-idle {
    animation: anim-idle 4s ease-in-out infinite;
}
.character.anim-shake {
    animation: anim-shake 0.5s ease-in-out;
}
.character.anim-bounce {
    animation: anim-bounce 0.6s ease-in-out;
}
.character.anim-pulse {
    animation: anim-pulse 1s ease-in-out infinite;
}
.speech-bubble {
    position: absolute;
    bottom: 18px;
    left: 50%;
    transform: translateX(-50%);
    min-width: 60%;
    max-width: 90%;
    padding: 20px 24px;
    border-radius: 20px;
    background: rgba(15,23,42,0.88);
    color: #f8fafc;
    font-family: "Atkinson Hyperlegible", system-ui, sans-serif;
    box-shadow: 0 10px 28px rgba(0,0,0,0.35);
    z-index: 20;
}
.speech-bubble::after {
    content: "";
    position: absolute;
    bottom: -16px;
    left: 50%;
    transform: translateX(-50%);
    border-width: 16px 12px 0 12px;
    border-style: solid;
    border-color: rgba(15,23,42,0.88) transparent transparent transparent;
}
.bubble-speaker {
    font-size: 0.85rem;
    letter-spacing: 0.08em;
    font-weight: 700;
    text-transform: uppercase;
    color: #facc15;
    margin-bottom: 6px;
}
.bubble-text {
    font-size: 1.05rem;
    line-height: 1.5;
}
.camera-column {
    position: relative;
    min-height: 360px;
    gap: 0.75rem;
}
.camera-hint {
    font-size: 0.85rem;
    color: #cbd5f5;
    margin-bottom: 0.4rem;
}
#camera-wrapper {
    width: 100%;
    max-width: 320px;
}
#camera-wrapper > div {
    border-radius: 18px;
    background: rgba(15,23,42,0.88);
    padding: 6px;
    box-shadow: 0 12px 26px rgba(15,23,42,0.55);
}
#camera-wrapper video {
    border-radius: 14px;
    object-fit: cover;
    box-shadow: 0 10px 30px rgba(0,0,0,0.4);
}
.dxl-card {
    margin-top: 0.5rem;
    padding: 1rem 1.2rem;
    border-radius: 14px;
    background: rgba(15,23,42,0.85);
    color: #e2e8f0;
    box-shadow: 0 10px 26px rgba(0,0,0,0.45);
}
.dxl-card h3 {
    margin: 0 0 0.35rem 0;
}
.dxl-row {
    display: flex;
    gap: 0.6rem;
    align-items: center;
    margin-bottom: 0.5rem;
    flex-wrap: wrap;
}
.dxl-row label {
    font-size: 0.9rem;
    color: #cbd5e1;
}
.dxl-row input[type="number"],
.dxl-row select,
.dxl-row input[type="range"] {
    flex: 1;
    min-width: 120px;
}
.dxl-btn {
    padding: 0.5rem 0.8rem;
    border-radius: 10px;
    border: 1px solid rgba(148,163,184,0.4);
    background: rgba(255,255,255,0.05);
    color: #e2e8f0;
    cursor: pointer;
    transition: transform 0.1s ease, background 0.15s ease;
}
.dxl-btn.primary {
    background: linear-gradient(120deg, #06b6d4, #2563eb);
    border-color: rgba(59,130,246,0.5);
}
.dxl-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
.dxl-btn:not(:disabled):hover {
    transform: translateY(-1px);
}
.dxl-status {
    font-size: 0.9rem;
    color: #a5b4fc;
    min-height: 1.2rem;
}
.input-prompt {
    font-size: 1.1rem;
    font-weight: 600;
    color: #1e293b;
    margin-bottom: 0.5rem;
}
@keyframes anim-idle {
    0% { transform: translate(-50%, 0px) scale(var(--char-scale)); }
    50% { transform: translate(-50%, 12px) scale(var(--char-scale)); }
    100% { transform: translate(-50%, 0px) scale(var(--char-scale)); }
}
@keyframes anim-shake {
    0%, 100% { transform: translate(-50%, 0) rotate(0deg) scale(var(--char-scale)); }
    10%, 30%, 50%, 70%, 90% { transform: translate(-52%, 0) rotate(-2deg) scale(var(--char-scale)); }
    20%, 40%, 60%, 80% { transform: translate(-48%, 0) rotate(2deg) scale(var(--char-scale)); }
}
@keyframes anim-bounce {
    0%, 100% { transform: translate(-50%, 0) scale(var(--char-scale)); }
    25% { transform: translate(-50%, -30px) scale(var(--char-scale)); }
    50% { transform: translate(-50%, 0) scale(var(--char-scale)); }
    75% { transform: translate(-50%, -15px) scale(var(--char-scale)); }
}
@keyframes anim-pulse {
    0%, 100% { transform: translate(-50%, 0) scale(var(--char-scale)); }
    50% { transform: translate(-50%, 0) scale(calc(var(--char-scale) * 1.05)); }
}
"""

ENUMERATE_CAMERAS_JS = """
async (currentDevices) => {
    if (!navigator.mediaDevices?.enumerateDevices) {
        return currentDevices || [];
    }
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        return devices
            .filter((device) => device.kind === "videoinput")
            .map((device, index) => ({
                label: device.label || `Camera ${index + 1}`,
                deviceId: device.deviceId || null,
            }));
    } catch (error) {
        console.warn("enumerateDevices failed", error);
        return currentDevices || [];
    }
}
"""

def load_dxl_script_js() -> str:
    """Inline the DXL script content directly."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    js_path = os.path.join(script_dir, "web", "dxl_webserial.js")

    try:
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
    except Exception as e:
        js_content = f"console.error('[DXL] Failed to load script: {e}');"

    # Properly escape for JavaScript template literal
    js_content_escaped = js_content.replace('\\', '\\\\').replace('`', '\\`').replace('${', '\\${')

    return f"""
() => {{
    try {{
        // Execute inline script
        const scriptFn = new Function({repr(js_content)});
        scriptFn();
        console.log('[DXL] Script loaded inline');
    }} catch(e) {{
        console.error('[DXL] Failed to execute:', e);
    }}
}}
"""


def dxl_send_and_receive_js() -> str:
    """JavaScript to send packet bytes and receive response via Web Serial."""
    return """
async (packet_bytes) => {
    // Check if dxlSerial is available and connected
    if (typeof window.dxlSerial === 'undefined' || !window.dxlSerial) {
        console.error("[DXL] Serial not available - connect first");
        return [];
    }

    if (!window.dxlSerial.connected) {
        console.error("[DXL] Not connected to serial port");
        return [];
    }

    try {
        await window.dxlSerial.writeBytes(packet_bytes);
        const response = await window.dxlSerial.readPacket(800);
        return response;
    } catch (err) {
        console.error("[DXL] Communication error:", err.message);
        return [];
    }
}
"""


def execute_motor_packets_js() -> str:
    """JavaScript to execute pre-built motor packets."""
    return """
async (packets) => {
    if (!packets || packets.length === 0) {
        return;  // No packets to execute
    }

    // Check if serial is available
    if (typeof window.dxlSerial === 'undefined' || !window.dxlSerial || !window.dxlSerial.connected) {
        return;  // Silently skip if not connected
    }

    // Execute each packet sequentially
    for (const pkt of packets) {
        try {
            await window.dxlSerial.writeBytes(pkt);
            await window.dxlSerial.readPacket(800);
        } catch (err) {
            console.error(`[Motors] Error:`, err.message);
        }
    }
}
"""


def play_scene_audio_js() -> str:
    """JavaScript to play audio file."""
    return """
(audio_path) => {
    if (!audio_path || audio_path === '') {
        return;  // No audio to play
    }

    // Create or reuse audio element
    let audio = document.getElementById('scene-audio-player');
    if (!audio) {
        audio = new Audio();
        audio.id = 'scene-audio-player';
    }

    console.log('[Audio] Playing:', audio_path);
    audio.src = audio_path;

    // Try to play with better error handling for HuggingFace Spaces
    audio.play()
        .then(() => console.log('[Audio] Playback started successfully'))
        .catch(err => {
            console.error('[Audio] Playback failed:', err.message);
            console.error('[Audio] Note: Browsers may block autoplay. User interaction may be required.');
        });
}
"""


def load_robot_ws_script_js() -> str:
    """JavaScript to initialize WebSocket connection to Reachy Mini robot."""
    return """
() => {
    console.log('[Robot] Initializing WebSocket connection...');

    // Define global initialization function if not already defined
    if (!window.loadRobotWebSocket) {
        window.loadRobotWebSocket = function() {
    const hostDiv = document.getElementById('robot-ws-host');
    if (!hostDiv) {
        console.error('[Robot] Cannot initialize - host div not found');
        return;
    }

    const ROBOT_URL = 'localhost:8000';
    const WS_URL = `ws://${ROBOT_URL}/api/move/ws/set_target`;

    console.log('[Robot] Connecting to:', WS_URL);

    // Global robot state
    window.reachyRobot = {
        ws: null,
        connected: false
    };

    // Create UI
    hostDiv.innerHTML = `
        <div id="robot-connection-status" style="padding: 8px; border-radius: 4px; background: #f8d7da; color: #721c24; margin-bottom: 10px;">
            <span id="robot-status-dot" style="display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #dc3545; margin-right: 6px;"></span>
            <span id="robot-status-text">Disconnected - Trying to connect...</span>
        </div>
    `;

    function updateStatus(connected) {
        const statusDiv = document.getElementById('robot-connection-status');
        const dot = document.getElementById('robot-status-dot');
        const text = document.getElementById('robot-status-text');

        if (connected) {
            statusDiv.style.background = '#d4edda';
            statusDiv.style.color = '#155724';
            dot.style.background = '#28a745';
            dot.style.boxShadow = '0 0 10px #28a745';
            text.textContent = 'Connected to robot';
        } else {
            statusDiv.style.background = '#f8d7da';
            statusDiv.style.color = '#721c24';
            dot.style.background = '#dc3545';
            dot.style.boxShadow = 'none';
            text.textContent = 'Disconnected - Reconnecting...';
        }
    }

    function connectWebSocket() {
        console.log('[Robot] Connecting to WebSocket:', WS_URL);

        window.reachyRobot.ws = new WebSocket(WS_URL);

        window.reachyRobot.ws.onopen = () => {
            console.log('[Robot] WebSocket connected');
            window.reachyRobot.connected = true;
            updateStatus(true);
        };

        window.reachyRobot.ws.onclose = () => {
            console.log('[Robot] WebSocket disconnected');
            window.reachyRobot.connected = false;
            updateStatus(false);
            // Reconnect after 2 seconds
            setTimeout(connectWebSocket, 2000);
        };

        window.reachyRobot.ws.onerror = (error) => {
            console.error('[Robot] WebSocket error:', error);
        };

        window.reachyRobot.ws.onmessage = (event) => {
            try {
                const message = JSON.parse(event.data);
                if (message.status === 'error') {
                    console.error('[Robot] Server error:', message.detail);
                }
            } catch (e) {
                console.error('[Robot] Failed to parse message:', e);
            }
        };
    }

    connectWebSocket();
        };  // End of window.loadRobotWebSocket definition
    }

    // Try to initialize (with multiple retries)
    let retryCount = 0;
    const maxRetries = 10;

    function tryInit() {
        const hostDiv = document.getElementById('robot-ws-host');
        if (!hostDiv) {
            retryCount++;
            if (retryCount <= maxRetries) {
                console.warn(`[Robot] Host div not found, retry ${retryCount}/${maxRetries} in 1 second`);
                setTimeout(tryInit, 1000);
            } else {
                console.warn('[Robot] Gave up waiting for robot widget div. Will initialize on first use.');
            }
            return;
        }

        if (window.reachyRobot) {
            console.log('[Robot] Already initialized');
            return;
        }

        // Initialize now
        console.log('[Robot] Found host div, initializing...');
        window.loadRobotWebSocket();
    }

    tryInit();
}
"""


def send_robot_pose_js() -> str:
    """JavaScript to send robot pose via WebSocket."""
    return """
async (pose_data) => {
    if (!pose_data) {
        return;  // No pose to send
    }

    // Initialize WebSocket if not already done (lazy initialization)
    if (!window.reachyRobot) {
        console.log('[Robot] Lazy initialization on first pose send');
        if (window.loadRobotWebSocket) {
            window.loadRobotWebSocket();
            // Wait a bit for connection to establish
            await new Promise(resolve => setTimeout(resolve, 500));
        }
    }

    if (!window.reachyRobot || !window.reachyRobot.connected || !window.reachyRobot.ws || window.reachyRobot.ws.readyState !== WebSocket.OPEN) {
        console.warn('[Robot] WebSocket not connected, skipping pose command');
        return;
    }

    try {
        console.log('[Robot] Sending pose:', pose_data);
        window.reachyRobot.ws.send(JSON.stringify(pose_data));
    } catch (error) {
        console.error('[Robot] Failed to send pose:', error);
    }
}
"""



def build_app() -> gr.Blocks:
    with gr.Blocks(title="Gradio Visual Novel") as demo:
        gr.HTML(f"<style>{CUSTOM_CSS}</style>", elem_id="vn-styles")
        story_state = gr.State()

        with gr.Row():
            with gr.Column(scale=3, min_width=640):
                stage = gr.HTML(label="Stage", elem_id="stage-container")
                dialogue = gr.Markdown(label="Dialogue")
                meta = gr.Markdown(label="Scene Info", elem_id="scene-info")

                # Choice selection
                choice_radio = gr.Radio(label="Make a choice", visible=False)

                # Text input
                with gr.Group(visible=False) as input_group:
                    input_prompt = gr.Markdown("", elem_classes=["input-prompt"])
                    with gr.Row():
                        user_input = gr.Textbox(label="Your answer", scale=4)
                        input_submit_btn = gr.Button("Submit", variant="primary", scale=1)

                with gr.Row():
                    prev_btn = gr.Button("⟵ Back", variant="secondary")
                    next_btn = gr.Button("Next ⟶", variant="primary")
            with gr.Column(scale=1, min_width=320, elem_classes=["camera-column"], visible=False) as right_column:
                gr.Markdown("### Live Camera (WebRTC)")
                camera_hint = gr.Markdown(
                    camera_hint_text(False), elem_classes=["camera-hint"]
                )
                gr.Markdown(
                    "Allow camera access when prompted. The webcam appears only in scenes that request it.",
                    elem_classes=["camera-hint"],
                )
                with gr.Group(elem_id="camera-wrapper"):
                    webrtc_component = WebRTC(
                        label="Webcam Stream",
                        mode="send-receive",
                        modality="video",
                        full_screen=False,
                        visible=False,
                    )
                webrtc_component.stream(
                    fn=passthrough_stream,
                    inputs=[webrtc_component],
                    outputs=[webrtc_component],
                )
                voice_hint = gr.Markdown(
                    voice_hint_text(False), elem_classes=["camera-hint"]
                )
                with gr.Group(visible=False, elem_id="voice-wrapper") as voice_section:
                    with gr.Accordion("Voice & Audio Agent", open=True):
                        gr.Markdown(
                            "Record a short line to pass to your AI companion. "
                            "We play back your clip and a synthetic confirmation tone.",
                            elem_classes=["camera-hint"],
                        )
                        voice_prompt = gr.Textbox(
                            label="Prompt/context",
                            value="React to the current scene with a friendly reply.",
                            lines=2,
                        )
                        mic = gr.Audio(
                            sources=["microphone", "upload"],
                            type="numpy",
                            label="Record or upload audio",
                        )
                        send_voice_btn = gr.Button(
                            "Send to voice agent", variant="secondary"
                        )
                        voice_summary = gr.Markdown("No audio captured yet.")
                        playback = gr.Audio(label="Your recording", interactive=False)
                        ai_voice_text = gr.Markdown("AI response will appear here.")
                        ai_voice_audio = gr.Audio(
                            label="AI voice reply (synthetic tone)", interactive=False
                        )
                        send_voice_btn.click(
                            fn=process_voice_interaction,
                            inputs=[mic, voice_prompt],
                            outputs=[
                                voice_summary,
                                playback,
                                ai_voice_text,
                                ai_voice_audio,
                            ],
                        )
                motor_hint = gr.Markdown(
                    motor_hint_text(False), elem_classes=["camera-hint"]
                )
                with gr.Group(visible=False, elem_id="dxl-panel-container") as motor_group:
                    with gr.Accordion("Dynamixel XL330 Control", open=True):
                        gr.Markdown(
                            "**Web Serial Control** - Use Chrome/Edge desktop. Connect to serial port, then control motors.",
                            elem_classes=["camera-hint"],
                        )

                        # Serial connection panel (still handled by JavaScript)
                        gr.HTML('<div id="dxl-panel-host"></div>', elem_id="dxl-panel-host-wrapper")

                        # Motor control inputs (Python-based)
                        with gr.Row():
                            motor_id_input = gr.Number(
                                label="Motor ID",
                                value=1,
                                minimum=0,
                                maximum=252,
                                precision=0,
                            )
                        with gr.Row():
                            goal_slider = gr.Slider(
                                label="Goal Position (degrees)",
                                minimum=0,
                                maximum=360,
                                value=90,
                                step=1,
                            )
                        with gr.Row():
                            ping_btn = gr.Button("Ping", size="sm")
                            torque_on_btn = gr.Button("Torque ON", size="sm", variant="secondary")
                            torque_off_btn = gr.Button("Torque OFF", size="sm")
                        with gr.Row():
                            send_goal_btn = gr.Button("Send Goal Position", variant="primary")
                        motor_status = gr.Markdown("Status: Ready")

                # Robot Control (Reachy Mini via WebSocket)
                robot_hint = gr.Markdown(
                    robot_hint_text(False), elem_classes=["camera-hint"]
                )
                with gr.Group(visible=False, elem_id="robot-panel-container") as robot_group:
                    with gr.Accordion("Reachy Mini Robot Control", open=True):
                        gr.Markdown(
                            "**WebSocket Control** - Connects to localhost:8000 for real-time robot control.",
                            elem_classes=["camera-hint"],
                        )

                        # WebSocket connection area (will be managed by JavaScript)
                        # Status is shown dynamically by JavaScript inside this div
                        gr.HTML('<div id="robot-ws-host"></div>', elem_id="robot-ws-host-wrapper")

        # Wire up event handlers
        all_outputs = [
            story_state,
            stage,
            dialogue,
            meta,
            camera_hint,
            webrtc_component,
            voice_hint,
            voice_section,
            motor_hint,
            motor_group,
            robot_hint,
            robot_group,
            choice_radio,
            input_prompt,
            input_group,
            user_input,  # Add user_input to clear it after submission
            prev_btn,
            next_btn,
            right_column,
        ]

        # Hidden JSON for passing packet bytes between Python and JavaScript
        # Note: gr.State doesn't work well with JavaScript, so we use JSON
        packet_bytes_json = gr.JSON(visible=False, value=[])
        response_bytes_json = gr.JSON(visible=False, value=[])
        motor_packets_json = gr.JSON(visible=False, value=[])  # For scene motor commands

        # Hidden textbox for passing audio path to JavaScript
        audio_path_box = gr.Textbox(visible=False, value="")

        # Hidden JSON for passing robot pose to JavaScript
        robot_pose_json = gr.JSON(visible=False, value=None)

        # Load initialization scripts
        combined_init_js = f"""
() => {{
    // Initialize Dynamixel
    ({load_dxl_script_js()})();
    // Initialize Robot WebSocket
    ({load_robot_ws_script_js()})();
}}
"""

        demo.load(
            fn=load_initial_state,
            inputs=None,
            outputs=all_outputs,
            js=combined_init_js,
        )

        # Navigation buttons with automatic motor command execution, audio playback, and robot control
        # Create parallel chains for audio, motors, and robot to ensure all get the updated state

        # Previous button
        prev_event = prev_btn.click(
            fn=lambda state: change_scene(state, -1),
            inputs=story_state,
            outputs=all_outputs,
        )
        # Audio chain
        prev_event.then(
            fn=get_scene_audio,
            inputs=[story_state],
            outputs=[audio_path_box],
        ).then(
            fn=None,
            inputs=[audio_path_box],
            outputs=[],
            js=play_scene_audio_js(),
        )
        # Motor chain (parallel)
        prev_event.then(
            fn=get_scene_motor_packets,
            inputs=[story_state],
            outputs=[motor_packets_json],
        ).then(
            fn=None,
            inputs=[motor_packets_json],
            outputs=[],
            js=execute_motor_packets_js(),
        )
        # Robot chain (parallel)
        prev_event.then(
            fn=get_scene_robot_pose,
            inputs=[story_state],
            outputs=[robot_pose_json],
        ).then(
            fn=None,
            inputs=[robot_pose_json],
            outputs=[],
            js=send_robot_pose_js(),
        )

        # Next button
        next_event = next_btn.click(
            fn=lambda state: change_scene(state, 1),
            inputs=story_state,
            outputs=all_outputs,
        )
        # Audio chain
        next_event.then(
            fn=get_scene_audio,
            inputs=[story_state],
            outputs=[audio_path_box],
        ).then(
            fn=None,
            inputs=[audio_path_box],
            outputs=[],
            js=play_scene_audio_js(),
        )
        # Motor chain (parallel)
        next_event.then(
            fn=get_scene_motor_packets,
            inputs=[story_state],
            outputs=[motor_packets_json],
        ).then(
            fn=None,
            inputs=[motor_packets_json],
            outputs=[],
            js=execute_motor_packets_js(),
        )
        # Robot chain (parallel)
        next_event.then(
            fn=get_scene_robot_pose,
            inputs=[story_state],
            outputs=[robot_pose_json],
        ).then(
            fn=None,
            inputs=[robot_pose_json],
            outputs=[],
            js=send_robot_pose_js(),
        )

        # Choice handler
        choice_event = choice_radio.change(
            fn=handle_choice,
            inputs=[story_state, choice_radio],
            outputs=all_outputs,
        )
        # Audio chain
        choice_event.then(
            fn=get_scene_audio,
            inputs=[story_state],
            outputs=[audio_path_box],
        ).then(
            fn=None,
            inputs=[audio_path_box],
            outputs=[],
            js=play_scene_audio_js(),
        )
        # Motor chain (parallel)
        choice_event.then(
            fn=get_scene_motor_packets,
            inputs=[story_state],
            outputs=[motor_packets_json],
        ).then(
            fn=None,
            inputs=[motor_packets_json],
            outputs=[],
            js=execute_motor_packets_js(),
        )
        # Robot chain (parallel)
        choice_event.then(
            fn=get_scene_robot_pose,
            inputs=[story_state],
            outputs=[robot_pose_json],
        ).then(
            fn=None,
            inputs=[robot_pose_json],
            outputs=[],
            js=send_robot_pose_js(),
        )

        # Input submit button
        input_submit_event = input_submit_btn.click(
            fn=handle_input,
            inputs=[story_state, user_input],
            outputs=all_outputs,
        )
        # Audio chain
        input_submit_event.then(
            fn=get_scene_audio,
            inputs=[story_state],
            outputs=[audio_path_box],
        ).then(
            fn=None,
            inputs=[audio_path_box],
            outputs=[],
            js=play_scene_audio_js(),
        )
        # Motor chain (parallel)
        input_submit_event.then(
            fn=get_scene_motor_packets,
            inputs=[story_state],
            outputs=[motor_packets_json],
        ).then(
            fn=None,
            inputs=[motor_packets_json],
            outputs=[],
            js=execute_motor_packets_js(),
        )
        # Robot chain (parallel)
        input_submit_event.then(
            fn=get_scene_robot_pose,
            inputs=[story_state],
            outputs=[robot_pose_json],
        ).then(
            fn=None,
            inputs=[robot_pose_json],
            outputs=[],
            js=send_robot_pose_js(),
        )

        # Input enter key
        input_enter_event = user_input.submit(
            fn=handle_input,
            inputs=[story_state, user_input],
            outputs=all_outputs,
        )
        # Audio chain
        input_enter_event.then(
            fn=get_scene_audio,
            inputs=[story_state],
            outputs=[audio_path_box],
        ).then(
            fn=None,
            inputs=[audio_path_box],
            outputs=[],
            js=play_scene_audio_js(),
        )
        # Motor chain (parallel)
        input_enter_event.then(
            fn=get_scene_motor_packets,
            inputs=[story_state],
            outputs=[motor_packets_json],
        ).then(
            fn=None,
            inputs=[motor_packets_json],
            outputs=[],
            js=execute_motor_packets_js(),
        )
        # Robot chain (parallel)
        input_enter_event.then(
            fn=get_scene_robot_pose,
            inputs=[story_state],
            outputs=[robot_pose_json],
        ).then(
            fn=None,
            inputs=[robot_pose_json],
            outputs=[],
            js=send_robot_pose_js(),
        )

        # Motor control event handlers
        # Pattern: Python builds packet -> JS sends/receives -> Python parses

        # Ping button
        ping_btn.click(
            fn=dxl_build_ping_packet,
            inputs=[motor_id_input],
            outputs=[packet_bytes_json],
        ).then(
            fn=None,
            inputs=[packet_bytes_json],
            outputs=[response_bytes_json],
            js=dxl_send_and_receive_js(),
        ).then(
            fn=dxl_parse_response,
            inputs=[response_bytes_json],
            outputs=[motor_status],
        )

        # Torque ON button
        torque_on_btn.click(
            fn=lambda motor_id: dxl_build_torque_packet(motor_id, True),
            inputs=[motor_id_input],
            outputs=[packet_bytes_json],
        ).then(
            fn=None,
            inputs=[packet_bytes_json],
            outputs=[response_bytes_json],
            js=dxl_send_and_receive_js(),
        ).then(
            fn=dxl_parse_response,
            inputs=[response_bytes_json],
            outputs=[motor_status],
        )

        # Torque OFF button
        torque_off_btn.click(
            fn=lambda motor_id: dxl_build_torque_packet(motor_id, False),
            inputs=[motor_id_input],
            outputs=[packet_bytes_json],
        ).then(
            fn=None,
            inputs=[packet_bytes_json],
            outputs=[response_bytes_json],
            js=dxl_send_and_receive_js(),
        ).then(
            fn=dxl_parse_response,
            inputs=[response_bytes_json],
            outputs=[motor_status],
        )

        # Send goal position button
        send_goal_btn.click(
            fn=dxl_build_goal_position_packet,
            inputs=[motor_id_input, goal_slider],
            outputs=[packet_bytes_json],
        ).then(
            fn=None,
            inputs=[packet_bytes_json],
            outputs=[response_bytes_json],
            js=dxl_send_and_receive_js(),
        ).then(
            fn=dxl_parse_response,
            inputs=[response_bytes_json],
            outputs=[motor_status],
        )

    return demo


def main() -> None:
    """Launch the Visual Novel Gradio app."""
    logger.info("=== Visual Novel App Startup ===")
    logger.info("Using HuggingFace repo URLs for assets")

    # Build Gradio app
    demo = build_app()

    # Enable queue for HuggingFace Spaces (required for proper component updates)
    demo.queue(default_concurrency_limit=10)

    # Launch with SSR disabled
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        ssr_mode=False,
        show_error=True,
    )



if __name__ == "__main__":
    main()
