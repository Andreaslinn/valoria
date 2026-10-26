from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alert_acknowledgements_follow_production_history_revision():
    root = Path(__file__).resolve().parents[2]
    cfg = Config()
    cfg.set_main_option("script_location", str(root / "alembic"))
    scripts = ScriptDirectory.from_config(cfg)
    assert scripts.get_heads() == ["0022"]
    assert Path(scripts.get_revision("0021").path).name == "0021_listing_observations.py"
    assert scripts.get_revision("0022").down_revision == "0021"
