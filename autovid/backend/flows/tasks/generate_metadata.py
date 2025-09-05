from pathlib import Path
from autovid.backend.flows.config.celery_app import app

from autovid.backend.flows.steps.metadata import MetadataManager
from autovid.backend.flows.utils.logging import with_stage_logging

@app.task(queue="metadata")
@with_stage_logging("metadata")
def generate_metadata(project_id: int):
    metadata_manager = MetadataManager()
    metadata = metadata_manager.generate_and_update_metadata(project_id)
    
    return metadata 