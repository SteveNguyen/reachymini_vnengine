"""Visual Novel Engine - Core classes and builder for creating interactive stories."""

from __future__ import annotations

import copy
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_BACKGROUND = "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=1200&q=80"

# Test URL to verify external images work
TEST_IMAGE_URL = "https://picsum.photos/1200/800"
POSITION_OFFSETS = {
    "left": "20%",
    "center": "50%",
    "right": "80%",
}


# HuggingFace Space configuration
HF_SPACE_REPO = "cduss/reachymini_vn_example"
HF_BASE_URL = f"https://huggingface.co/spaces/{HF_SPACE_REPO}/resolve/main"

# Asset helper functions - HuggingFace repo URLs
def background_asset(filename: str) -> str:
    """Get the URL for a background image from HF repo."""
    url = f"{HF_BASE_URL}/assets/backgrounds/{filename}"
    logger.info(f"Background asset: {url}")
    return url


def sprite_asset(filename: str) -> str:
    """Get the URL for a sprite image from HF repo."""
    url = f"{HF_BASE_URL}/assets/sprites/{filename}"
    logger.info(f"Sprite asset: {url}")
    return url


def audio_asset(filename: str) -> str:
    """Get the URL for an audio file from HF repo."""
    url = f"{HF_BASE_URL}/assets/audio/{filename}"
    logger.info(f"Audio asset: {url}")
    return url


def create_sprite_data_url(bg_color: str = "#fef3c7", border_color: str = "#ea580c") -> str:
    """Create a simple inline SVG data-URI for a character sprite."""
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="200" height="400" viewBox="0 0 200 400">
      <rect width="200" height="400" fill="{bg_color}" rx="20"/>
      <circle cx="100" cy="120" r="50" fill="{border_color}" opacity="0.6"/>
      <rect x="60" y="180" width="80" height="140" fill="{border_color}" opacity="0.4" rx="10"/>
    </svg>"""
    encoded = svg.replace('"', '%22').replace('#', '%23').replace('<', '%3C').replace('>', '%3E')
    return f"data:image/svg+xml,{encoded}"


@dataclass
class CharacterDefinition:
    name: str
    image_url: str
    animated: bool = False


@dataclass
class CharacterSprite:
    name: str
    image_url: str
    position: str = "center"
    visible: bool = False
    animation: str = ""  # Animation type: "", "idle", "shake", "bounce", "pulse"
    scale: float = 1.0  # Scale multiplier (1.0 = 100%, 0.5 = 50%, 2.0 = 200%)


@dataclass
class Choice:
    text: str
    next_scene_index: int


@dataclass
class InputRequest:
    prompt: str
    variable_name: str


@dataclass
class MotorCommand:
    motor_id: int
    position: int  # Position in degrees (0-360)


@dataclass
class RobotPose:
    """Robot pose command for Reachy Mini control."""
    head_x: float = 0.0  # meters
    head_y: float = 0.0  # meters
    head_z: float = 0.0  # meters
    head_roll: float = 0.0  # radians
    head_pitch: float = 0.0  # radians
    head_yaw: float = 0.0  # radians
    body_yaw: float = 0.0  # radians
    antenna_left: float = 0.0  # radians
    antenna_right: float = 0.0  # radians


@dataclass
class SceneState:
    background_url: str
    background_label: str
    characters: Dict[str, CharacterSprite]
    speaker: str
    text: str
    note: str
    show_camera: bool = False
    show_voice: bool = False
    show_motors: bool = False
    show_robot: bool = False  # Show robot control widget
    background_blur: int = 0  # Blur amount in pixels (0 = no blur, 5-10 = good range)
    stage_url: str = ""  # Stage image on top of background, below characters
    stage_blur: int = 0  # Blur amount for stage layer
    choices: Optional[List[Choice]] = None
    input_request: Optional[InputRequest] = None
    path: Optional[str] = None  # Which story branch this scene belongs to
    motor_commands: List[MotorCommand] = field(default_factory=list)  # Commands to execute on scene entry
    audio_file: Optional[str] = None  # Audio file to play when scene is displayed
    robot_pose: Optional[RobotPose] = None  # Robot pose to send when scene is displayed


class VisualNovelBuilder:
    """Builder to construct a linear or branching visual novel scene-by-scene."""

    def __init__(self) -> None:
        self._states: List[SceneState] = []
        self._character_defs: Dict[str, CharacterDefinition] = {}
        self._current_background: str = DEFAULT_BACKGROUND
        self._current_label: str = ""
        self._current_sprites: Dict[str, CharacterSprite] = {}
        self._current_show_camera: bool = False
        self._current_show_voice: bool = False
        self._current_show_motors: bool = False
        self._current_show_robot: bool = False
        self._current_background_blur: int = 0
        self._current_stage: str = ""
        self._current_stage_blur: int = 0
        self._current_path: Optional[str] = None

    def set_characters(self, characters: List[CharacterDefinition]) -> None:
        """Register character definitions (name, image_url, animated)."""
        for char in characters:
            self._character_defs[char.name] = char
            self._current_sprites[char.name] = CharacterSprite(
                name=char.name,
                image_url=char.image_url,
                position="center",
                visible=False,
                animation="idle" if char.animated else "",
            )

    def set_background(self, image_url: str, label: str = "") -> None:
        """Change the background image and optionally set a label."""
        state = self._clone_state()
        state.background_url = image_url
        state.background_label = label
        state.note = f"Background: {label or 'custom'}"
        self._push_state(state)

    def set_camera(self, show: bool) -> None:
        """Toggle the camera display for the next scene."""
        self._current_show_camera = show

    def set_voice(self, show: bool) -> None:
        """Toggle the voice capture UI for the next scene."""
        self._current_show_voice = show

    def set_motors(self, show: bool) -> None:
        """Toggle the motor control UI for the next scene."""
        self._current_show_motors = show

    def set_robot(self, show: bool) -> None:
        """Toggle the robot control UI for the next scene."""
        self._current_show_robot = show

    def set_background_blur(self, blur_amount: int) -> None:
        """Set the background blur amount in pixels (0 = no blur, 5-10 is typical range)."""
        self._current_background_blur = blur_amount

    def set_stage(self, image_url: str) -> None:
        """Set the stage image (layer between background and characters)."""
        self._current_stage = image_url

    def set_stage_blur(self, blur_amount: int) -> None:
        """Set the stage blur amount in pixels (0 = no blur, 5-10 is typical range)."""
        self._current_stage_blur = blur_amount

    def set_path(self, path: Optional[str]) -> None:
        """Set the story path for subsequent scenes."""
        self._current_path = path

    def show_character(self, name: str, position: str = "center") -> None:
        """Display a character at a specific position."""
        state = self._clone_state()
        if name in state.characters:
            state.characters[name].visible = True
            state.characters[name].position = position
        state.note = f"Show {name} at {position}"
        self._push_state(state)

    def hide_character(self, name: str) -> None:
        """Hide a character from the scene."""
        state = self._clone_state()
        if name in state.characters:
            state.characters[name].visible = False
        state.note = f"Hide {name}"
        self._push_state(state)

    def move_character(self, name: str, position: str) -> None:
        """Move a character to a new position."""
        state = self._clone_state()
        if name in state.characters:
            state.characters[name].position = position
        state.note = f"Move {name} to {position}"
        self._push_state(state)

    def change_character_sprite(self, name: str, image_url: str) -> None:
        """Change a character's sprite image (e.g., for different emotions)."""
        state = self._clone_state()
        if name in state.characters:
            state.characters[name].image_url = image_url
        state.note = f"Change {name} sprite"
        self._push_state(state)

    def set_character_animation(self, name: str, animation: str) -> None:
        """Set character animation. Options: '', 'idle', 'shake', 'bounce', 'pulse'."""
        state = self._clone_state()
        if name in state.characters:
            state.characters[name].animation = animation
        state.note = f"{name} animation: {animation or 'none'}"
        self._push_state(state)

    def set_character_scale(self, name: str, scale: float) -> None:
        """Set character scale. 1.0 = 100%, 0.5 = 50%, 2.0 = 200%."""
        state = self._clone_state()
        if name in state.characters:
            state.characters[name].scale = scale
        state.note = f"{name} scale: {scale}"
        self._push_state(state)

    def dialogue(self, speaker: str, text: str) -> None:
        """Add a dialogue line."""
        state = self._clone_state()
        state.speaker = speaker
        state.text = text
        state.note = f"{speaker}: {text[:30]}..."
        self._push_state(state)

    def narration(self, text: str) -> None:
        """Add narration (no speaker)."""
        state = self._clone_state()
        state.speaker = ""
        state.text = text
        state.note = f"Narration: {text[:30]}..."
        self._push_state(state)

    def request_input(self, prompt: str, variable_name: str) -> None:
        """Request text input from the user."""
        state = self._clone_state()
        state.input_request = InputRequest(prompt=prompt, variable_name=variable_name)
        state.note = f"Input: {variable_name}"
        self._push_state(state)

    def send_motor_command(self, motor_id: int, position: int) -> None:
        """Send a motor command when this scene is displayed."""
        state = self._clone_state()
        state.motor_commands.append(MotorCommand(motor_id=motor_id, position=position))
        state.note = f"Motor {motor_id} → {position}°"
        self._push_state(state)

    def send_motor_commands(self, commands: List[tuple[int, int]]) -> None:
        """Send multiple motor commands when this scene is displayed.

        Args:
            commands: List of (motor_id, position) tuples
        """
        state = self._clone_state()
        for motor_id, position in commands:
            state.motor_commands.append(MotorCommand(motor_id=motor_id, position=position))
        state.note = f"Motors: {len(commands)} commands"
        self._push_state(state)

    def send_robot_pose(
        self,
        head_x: float = 0.0,
        head_y: float = 0.0,
        head_z: float = 0.0,
        head_roll: float = 0.0,
        head_pitch: float = 0.0,
        head_yaw: float = 0.0,
        body_yaw: float = 0.0,
        antenna_left: float = 0.0,
        antenna_right: float = 0.0,
    ) -> None:
        """Send a robot pose command when this scene is displayed.

        Args:
            head_x: X position in meters
            head_y: Y position in meters
            head_z: Z position in meters
            head_roll: Roll angle in radians
            head_pitch: Pitch angle in radians
            head_yaw: Yaw angle in radians
            body_yaw: Body yaw angle in radians
            antenna_left: Left antenna angle in radians
            antenna_right: Right antenna angle in radians
        """
        state = self._clone_state()
        state.robot_pose = RobotPose(
            head_x=head_x,
            head_y=head_y,
            head_z=head_z,
            head_roll=head_roll,
            head_pitch=head_pitch,
            head_yaw=head_yaw,
            body_yaw=body_yaw,
            antenna_left=antenna_left,
            antenna_right=antenna_right,
        )
        state.note = "Robot pose command"
        self._push_state(state)

    def play_sound(self, audio_file: str) -> None:
        """Play an audio file when this scene is displayed.

        Args:
            audio_file: Path to audio file (relative to assets/audio/ or absolute path)
        """
        state = self._clone_state()
        state.audio_file = audio_file
        state.note = f"Audio: {audio_file}"
        self._push_state(state)

    def add_choice(self, text: str, next_scene_index: int) -> None:
        """Add a choice to the current scene (for branching)."""
        if self._states:
            if self._states[-1].choices is None:
                self._states[-1].choices = []
            self._states[-1].choices.append(Choice(text=text, next_scene_index=next_scene_index))

    def _clone_state(self) -> SceneState:
        """Clone the current state for the next scene."""
        return SceneState(
            background_url=self._current_background,
            background_label=self._current_label,
            characters=copy.deepcopy(self._current_sprites),
            speaker="",
            text="",
            note="",
            show_camera=self._current_show_camera,
            show_voice=self._current_show_voice,
            show_motors=self._current_show_motors,
            show_robot=self._current_show_robot,
            background_blur=self._current_background_blur,
            stage_url=self._current_stage,
            stage_blur=self._current_stage_blur,
            path=self._current_path,
        )

    def _push_state(self, state: SceneState) -> None:
        """Push a new state and update internal tracking."""
        self._states.append(state)
        self._current_background = state.background_url
        self._current_label = state.background_label
        self._current_sprites = copy.deepcopy(state.characters)

    def build(self) -> List[SceneState]:
        """Return the finalized list of scene states."""
        return self._states
