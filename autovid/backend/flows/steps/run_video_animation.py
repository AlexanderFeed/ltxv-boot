import sys
from autovid.backend.flows.steps.animate_scene import SceneAnimationManager

if __name__ == "__main__":
    project_id = sys.argv[1]
    video_format = sys.argv[2] if len(sys.argv) > 2 else "long"
    SceneAnimationManager(project_id, video_format).run()
