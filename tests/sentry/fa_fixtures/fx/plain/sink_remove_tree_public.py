from decoy_engine import fileaccess


def clean(path):
    fileaccess.remove_tree(path)
