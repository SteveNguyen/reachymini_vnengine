"""Sample Story - Example visual novel story with branching paths."""

import copy
from typing import List

from engine import (
    VisualNovelBuilder,
    SceneState,
    CharacterDefinition,
    Choice,
    background_asset,
    sprite_asset,
    audio_asset,
    create_sprite_data_url,
)


def build_sample_story() -> List[SceneState]:
    """Build the sample story with branching paths."""
    builder = VisualNovelBuilder()
    builder.set_characters(
        [
            CharacterDefinition(
                name="Ari",
                image_url=sprite_asset('reachy-mini-cartoon.svg'),
            ),
            CharacterDefinition(
                name="Bo",
                image_url=sprite_asset('ReachyMini_emotions_happy.svg'),
                animated=True,
            ),
        ]
    )
    builder.set_background(
        background_asset('workshop_bg.png'),
    )
    builder.set_stage(background_asset("p60-back-cover.png"))

    builder.narration("A hush falls over the academy courtyard as the gates creak open.")
    builder.set_stage(
        background_asset('p3.png'),
    )
    # Request player name
    builder.request_input("What is your name, traveler?", "player_name")

    # After input, create a new state without input_request
    state = builder._clone_state()
    state.input_request = None  # Clear the input request
    state.note = "Continuing story"
    builder._push_state(state)

    builder.show_character("Ari", position="left")
    builder.play_sound(audio_asset("wake_up.wav"))
    builder.dialogue("Ari", "Welcome, {player_name}! I'm Ari, and this is Bo.")
    builder.show_character("Bo", position="right")
    builder.dialogue("Bo", "Nice to meet you, {player_name}. We're on a quest to find the star fragment.")
    builder.dialogue("Ari", "Will you help us on our quest?")

    # ACCEPT BRANCH - tag all scenes with path="accept"
    accept_index = len(builder._states)
    builder.set_path("accept")
    builder.dialogue("Bo", "Excellent! We knew we could count on you, {player_name}!")
    builder.move_character("Ari", position="center")
    builder.narration("You join Ari and Bo on their adventure...")

    # Demonstrate camera feature
    builder.set_camera(True)
    builder.dialogue("Ari", "First, let me see your face, {player_name}. The camera will help us verify your identity.")
    builder.narration("The camera activates, showing your live feed...")

    # Demonstrate voice feature
    builder.set_camera(False)
    builder.set_voice(True)
    builder.dialogue("Bo", "Now, tell us about yourself using the voice recorder.")
    builder.narration("You can now record or upload audio to interact with the companions.")

    # Demonstrate motors feature
    builder.set_voice(False)
    builder.set_motors(True)
    builder.dialogue("Ari", "Finally, we need to test the portal controls. Use the motor panel to align the crystals.")
    builder.narration("Motor controls are now available. Adjust the servos to proceed.")

    # Example: Send motor commands from the story
    builder.send_motor_command(1, 90)  # Move motor ID 1 to 90 degrees
    builder.dialogue("Ari", "Watch as the first crystal aligns itself!")

    # Example: Send multiple motor commands at once
    builder.send_motor_commands([(1, 180), (2, 90)])  # Move motors 1 and 2
    builder.dialogue("Ari", "Now the portal crystals are synchronizing!")

    # Example: Play sound effect
    builder.play_sound(audio_asset("confused1.wav"))  # Uncomment when you add audio files
    builder.dialogue("Ari", "Listen! The portal resonates with magical energy!")

    # Demonstrate robot control (Reachy Mini)
    builder.set_motors(False)
    builder.set_robot(True)
    builder.dialogue("Bo", "Now let's test the Reachy Mini robot! It should be at localhost:8000.")
    builder.narration("The robot control panel appears. Make sure your Reachy Mini server is running.")

    # Send robot pose command - head looking up and antennas raised
    builder.send_robot_pose(
        head_x=0.0,
        head_y=0.0,
        head_z=0.02,  # Raise head 2cm
        head_pitch=-0.1,  # Look up (negative pitch)
        antenna_left=-0.2,  # Raise left antenna
        antenna_right=0.2,  # Raise right antenna
    )
    builder.dialogue("Ari", "Watch! The robot looks up in wonder!")

    # Send another pose - head tilted
    builder.send_robot_pose(
        head_z=-0.04,  # Raise head 2cm
        head_roll=0.1,  # Tilt head to the side
        head_yaw=0.1,  # Turn head slightly
        antenna_left=-0.3,  # Lower left antenna
        antenna_right=0.8,  # Raise right antenna more
    )
    builder.dialogue("Bo", "The robot is expressing curiosity!")

    # Demonstrate stage layer with separate blur
    builder.set_robot(False)
    builder.set_stage(background_asset('p3.png'))  # Add a stage layer
    builder.dialogue("Ari", "Look! The portal is opening...")
    builder.narration("A mystical stage appears between you and the background.")

    # Demonstrate separate blur controls
    builder.set_background_blur(8)
    builder.set_stage_blur(3)
    builder.dialogue("Ari", "Wait! Do you sense that? Something magical is happening...")
    builder.narration("The background and stage blur independently as Ari steps forward.")

    # Clear stage and blur
    builder.set_background_blur(0)
    builder.set_stage_blur(0)
    builder.set_stage("")  # Remove stage layer

    # Demonstrate character animations and sprite changes
    builder.set_character_animation("Bo", "shake")
    builder.dialogue("Bo", "Whoa! Did you feel that tremor?!")

    builder.set_character_animation("Bo", "bounce")
    builder.dialogue("Bo", "This is so exciting! We're getting close!")

    builder.set_character_animation("Bo", "")
    builder.set_character_animation("Ari", "pulse")
    builder.dialogue("Ari", "The star fragment... I can feel its power pulsing nearby.")

    # Demonstrate character scaling
    builder.set_character_animation("Ari", "")
    builder.set_character_scale("Ari", 1.5)
    builder.dialogue("Ari", "The power... it's making me grow stronger!")

    builder.set_character_scale("Bo", 0.7)
    builder.dialogue("Bo", "Whoa, you're getting really big! Or am I shrinking?")

    # Reset scales
    builder.set_character_scale("Ari", 1.0)
    builder.set_character_scale("Bo", 1.0)

    # Turn off all features
    builder.set_motors(False)
    builder.dialogue("Ari", "The portal is ready! But wait...")
    builder.dialogue("Bo", "The path splits here! We need to split up to cover more ground.")
    builder.dialogue("Ari", "You'll need to choose who to follow, {player_name}.")

    # SECOND CHOICE - Follow Ari or Bo
    # Remember the index before the branches
    follow_ari_index = len(builder._states)

    # FOLLOW ARI SUB-BRANCH
    builder.set_path("accept.follow_ari")
    builder.dialogue("Ari", "Wise choice! My path leads through the ancient library.")
    builder.hide_character("Bo")
    builder.move_character("Ari", position="center")
    builder.set_background(background_asset('p3.png'))
    builder.narration("Bo waves goodbye as you follow Ari into the misty corridors...")
    builder.dialogue("Ari", "The fragment's energy is strongest here. Stay close!")
    builder.set_character_animation("Ari", "pulse")
    builder.send_motor_command(1, 45)  # Different motor position for this path
    builder.dialogue("Ari", "The ancient mechanisms are responding!")
    builder.set_character_animation("Ari", "")
    builder.narration("You discover the star fragment hidden in an ancient tome.")
    builder.dialogue("Ari", "We did it, {player_name}! The knowledge was the key all along.")
    builder.play_sound(audio_asset("wake_up.wav"))
    builder.narration("✨ Ending: The Scholar's Path (Follow Ari)")

    # FOLLOW BO SUB-BRANCH
    follow_bo_index = len(builder._states)
    builder.set_path("accept.follow_bo")
    builder.dialogue("Bo", "Adventure time! My route goes through the crystal caves!")
    builder.hide_character("Ari")
    builder.move_character("Bo", position="center")
    builder.set_background(background_asset('workshop_bg.png'))
    builder.narration("Ari nods encouragingly as you follow Bo into the glowing caves...")
    builder.dialogue("Bo", "Can you feel the energy? It's electric!")
    builder.set_character_animation("Bo", "bounce")
    builder.send_motor_commands([(1, 135), (2, 135)])  # Different motor positions
    builder.dialogue("Bo", "The crystals are resonating! We're so close!")
    builder.set_character_animation("Bo", "shake")
    builder.narration("A powerful tremor shakes the cavern as the fragment reveals itself!")
    builder.dialogue("Bo", "Whoa! Grab it, {player_name}!")
    builder.set_character_animation("Bo", "")
    builder.play_sound(audio_asset("wake_up.wav"))
    builder.narration("✨ Ending: The Adventurer's Path (Follow Bo)")

    # Insert the second choice scene before the sub-branches
    second_choice_scene = copy.deepcopy(builder._states[follow_ari_index - 1])
    second_choice_scene.choices = [
        Choice(text="Follow Ari (Library)", next_scene_index=follow_ari_index),
        Choice(text="Follow Bo (Caves)", next_scene_index=follow_bo_index),
    ]
    second_choice_scene.note = "Second Choice (2 paths)"
    second_choice_scene.input_request = None
    second_choice_scene.path = "accept"  # This choice is within the accept path
    builder._states[follow_ari_index - 1] = second_choice_scene

    # DECLINE BRANCH - tag all scenes with path="decline"
    decline_index = len(builder._states)
    builder.set_path("decline")
    builder.dialogue("Ari", "That's... disappointing, {player_name}.")
    builder.hide_character("Bo")
    builder.dialogue("Ari", "I guess we're on our own, Bo.")
    builder.narration("Ari and Bo leave without you... (Decline path)")

    # Insert the choice scene before the branches
    choice_scene = copy.deepcopy(builder._states[accept_index - 1])
    choice_scene.choices = [
        Choice(text="Yes, I'll help!", next_scene_index=accept_index),
        Choice(text="No, sorry.", next_scene_index=decline_index),
    ]
    choice_scene.note = "Choice (2 options)"
    choice_scene.input_request = None  # Make sure no input request on choice scene
    choice_scene.path = None  # Choice scene is on the main path
    builder._states[accept_index - 1] = choice_scene

    return builder.build()
