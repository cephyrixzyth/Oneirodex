

class FakeOAuth:
    def __init__(self):
        self.clients = {}

    def init_app(self, app):
        self.app = app

    def register(self, **kwargs):
        self.clients[kwargs['name']] = kwargs


