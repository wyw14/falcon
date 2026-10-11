import pytest

import falcon
from falcon import testing


def test_custom_router_add_route_should_be_used(asgi, util):
    check = []

    class CustomRouter:
        def add_route(self, uri_template, *args, **kwargs):
            check.append(uri_template)

        def find(self, uri):
            pass

    app = util.create_app(asgi=asgi, router=CustomRouter())
    app.add_route('/test', 'resource')

    assert len(check) == 1
    assert '/test' in check


def test_custom_router_find_should_be_used(asgi, util):
    if asgi:

        async def resource(req, resp, **kwargs):
            resp.text = f'{{"uri_template": "{req.uri_template}"}}'

    else:

        def resource(req, resp, **kwargs):  # type: ignore[misc]
            resp.text = f'{{"uri_template": "{req.uri_template}"}}'

    class CustomRouter:
        def __init__(self):
            self.reached_backwards_compat = False

        def find(self, uri, req=None):
            if uri == '/test/42':
                return resource, {'GET': resource}, {}, '/test/{id}'

            if uri == '/test/42/no-uri-template':
                return resource, {'GET': resource}, {}, None

            if uri == '/test/42/uri-template/backwards-compat':
                return resource, {'GET': resource}, {}

            if uri == '/404/backwards-compat':
                self.reached_backwards_compat = True
                return (None, None, None)

            return None

    router = CustomRouter()
    app = util.create_app(asgi=asgi, router=router)
    client = testing.TestClient(app)

    response = client.simulate_request(path='/test/42')
    assert response.content == b'{"uri_template": "/test/{id}"}'

    response = client.simulate_request(path='/test/42/no-uri-template')
    assert response.content == b'{"uri_template": "None"}'

    response = client.simulate_request(path='/test/42/uri-template/backwards-compat')
    assert response.content == b'{"uri_template": "None"}'

    for uri in ('/404', '/404/backwards-compat'):
        response = client.simulate_request(path=uri)
        assert response.content == falcon.HTTPNotFound().to_json()
        assert response.status == falcon.HTTP_404

    assert router.reached_backwards_compat


def test_can_pass_additional_params_to_add_route(asgi, util):
    check = []

    class CustomRouter:
        def add_route(self, uri_template, resource, **kwargs):
            name = kwargs['name']
            self._index = {name: uri_template}
            check.append(name)

        def find(self, uri):
            pass

    app = util.create_app(asgi=asgi, router=CustomRouter())
    app.add_route('/test', 'resource', name='my-url-name')

    assert len(check) == 1
    assert 'my-url-name' in check

    # NOTE(kgriffs): Extra values must be passed as kwargs, since that makes
    #   it a lot easier for overridden methods to simply ignore options they
    #   don't care about.
    with pytest.raises(TypeError):
        app.add_route('/test', 'resource', 'xarg1', 'xarg2')


def test_custom_router_takes_req_positional_argument(asgi, util):
    if asgi:

        async def responder(req, resp):
            resp.text = 'OK'

    else:

        def responder(req, resp):  # type: ignore[misc]
            resp.text = 'OK'

    class CustomRouter:
        def find(self, uri, req):
            if uri == '/test' and isinstance(req, falcon.Request):
                return responder, {'GET': responder}, {}, None

    router = CustomRouter()
    app = util.create_app(asgi=asgi, router=router)
    client = testing.TestClient(app)
    response = client.simulate_request(path='/test')
    assert response.content == b'OK'


def test_custom_router_takes_req_keyword_argument(asgi, util):
    if asgi:

        async def responder(req, resp):
            resp.text = 'OK'

    else:

        def responder(req, resp):  # type: ignore[misc]
            resp.text = 'OK'

    class CustomRouter:
        def find(self, uri, req=None):
            if uri == '/test' and isinstance(req, falcon.Request):
                return responder, {'GET': responder}, {}, None

    router = CustomRouter()
    app = util.create_app(asgi=asgi, router=router)
    client = testing.TestClient(app)
    response = client.simulate_request(path='/test')
    assert response.content == b'OK'


def test_custom_router_sparse_method_map(asgi, util):
    if asgi:

        async def responder(req, resp):
            resp.text = 'OK'

    else:

        def responder(req, resp):  # type: ignore[misc]
            resp.text = 'OK'

    class CustomRouter:
        def find(self, uri, req=None):
            if uri == '/test':
                # NOTE: Intentionally sparse map, without default responders.
                return responder, {'GET': responder}, {}, None

            return None

    client = testing.TestClient(util.create_app(asgi=asgi, router=CustomRouter()))

    # NOTE: A matched route with an unsupported method is 405 (not 404/400).
    response = client.simulate_post('/test')
    assert response.status == falcon.HTTP_405
    assert response.headers['allow'] == 'GET, HEAD, OPTIONS'

    # NOTE: HEAD is synthesized from GET without a body.
    response = client.simulate_head('/test')
    assert response.status == falcon.HTTP_200
    assert not response.content
    assert response.headers['content-length'] == '2'

    # NOTE: A default OPTIONS responder is synthesized as well.
    response = client.simulate_options('/test')
    assert response.status == falcon.HTTP_200
    assert response.headers['allow'] == 'GET, HEAD'

    # NOTE: An unmatched route is still 404.
    response = client.simulate_get('/missing')
    assert response.status == falcon.HTTP_404


def test_custom_router_sparse_method_map_with_options(asgi, util):
    if asgi:

        async def responder(req, resp, **kwargs):
            resp.text = 'OK'

        async def options_responder(req, resp, **kwargs):
            resp.set_header('Allow', 'GET, OPTIONS')

    else:

        def responder(req, resp, **kwargs):  # type: ignore[misc]
            resp.text = 'OK'

        def options_responder(req, resp, **kwargs):  # type: ignore[misc]
            resp.set_header('Allow', 'GET, OPTIONS')

    class CustomRouter:
        def find(self, uri, req=None):
            if uri == '/test':
                # NOTE: Sparse map, with an explicit OPTIONS responder.
                return (
                    object(),
                    {'GET': responder, 'OPTIONS': options_responder},
                    {},
                    None,
                )

            return None

    client = testing.TestClient(util.create_app(asgi=asgi, router=CustomRouter()))

    response = client.simulate_post('/test')
    assert response.status == falcon.HTTP_405
    # NOTE: OPTIONS must not be duplicated when the map already lists it.
    assert response.headers['allow'] == 'GET, HEAD, OPTIONS'

    response = client.simulate_options('/test')
    assert response.status == falcon.HTTP_200
    assert response.headers['allow'] == 'GET, OPTIONS'


def test_custom_router_sparse_method_map_meta(asgi, util):
    def get_responder(req, resp, **kwargs):
        resp.text = 'OK'

    class CustomRouter:
        def find(self, uri, req=None):
            if uri == '/ws':
                # NOTE: Sparse map without a WEBSOCKET responder.
                return object(), {'GET': get_responder}, {}, '/ws'

            return None

    app = util.create_app(asgi=asgi, router=CustomRouter())
    req = util.create_req(asgi, path='/ws', method='GET')
    req.is_websocket = True

    default_responder, _, _, _ = app._get_responder(req)

    # NOTE: Meta methods keep the bad-request default responder.
    assert default_responder is type(app)._default_responder_bad_request

    resp = util.create_resp(asgi)
    with pytest.raises(falcon.HTTPBadRequest):
        if asgi:
            falcon.async_to_sync(default_responder, req, resp)
        else:
            default_responder(req, resp)
