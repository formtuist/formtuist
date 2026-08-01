class Auth:
    def verify(self, token):
        return self._check(token)

    def _check(self, token):
        return token == "secret"


def process(token):
    return "ok"


def handle_request(token):
    auth = Auth()
    if auth.verify(token):
        return process(token)
    return "denied"
