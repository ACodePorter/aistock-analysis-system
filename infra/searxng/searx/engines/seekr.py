# stub seekr engine to satisfy searxng import during startup

def setup(engine_data):
    return True


def search(query, params):
    return []
