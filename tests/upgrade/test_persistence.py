from intelx_upgrade.persistence import DurableResearchStore
def test_persistence(tmp_path):
    p=DurableResearchStore(str(tmp_path/"state.db"))
    assert p.save_state("t","r","{}","h",0)==1
