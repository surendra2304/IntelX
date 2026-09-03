from intelx_upgrade.checkpoint import *
def test_checkpoint():
    m=CheckpointManager(); c=Checkpoint("r","search",1,"h"); m.save(c); assert m.load("r")==c
