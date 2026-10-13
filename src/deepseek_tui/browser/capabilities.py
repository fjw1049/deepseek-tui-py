"""One capability contract for the runtime, observations and model guidance."""


def browser_capabilities(*, video_ready=False):
    return {
        "observation": {
            "frame_depth": 8,
            "open_shadow": True,
            "oopif": True,
            "shadow_frame_owners": True,
            "closed_shadow": False,
        },
        "recording": {
            "frame_depth": 8,
            "open_shadow": True,
            "oopif": True,
            "mask_all_inputs": True,
            "dynamic_frame_discovery": "requires_install_before_input",
        },
        "replay": {
            "frame_depth": 8,
            "open_shadow": True,
            "oopif": True,
            "multi_tab": "recorded_task_aliases",
            "preflight": "whole_workflow",
        },
        "input": {
            "native_keyboard_mouse": True,
            "frame_css_transforms": False,
            "coordinate_source": "unchanged_current_viewport_screenshot",
            "scene_bound_human_input": True,
        },
        "upload": "explicit_workspace_files_or_human_file_choice",
        "download": "thread_owned_directory",
        "native_dialogs": True,
        "video": {"ready": video_ready, "encoder": "ffmpeg", "fps": 5, "max_seconds": 180},
    }
