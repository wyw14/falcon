import pytest

import falcon
from falcon import constants
from falcon import testing
import falcon.asgi
from falcon.util.deprecation import DeprecatedWarning


def capture_error(req, resp, ex, params):
    resp.status = falcon.HTTP_723
    resp.text = f'error: {str(ex)}'


async def capture_error_async(*args):
    capture_error(*args)


def handle_error_first(req, resp, ex, params):
    resp.status = falcon.HTTP_200
    resp.text = 'first error handler'


class CustomBaseException(Exception):
    pass


class CustomException(CustomBaseException):
    @staticmethod
    def handle(req, resp, ex, params):
        raise falcon.HTTPError(
            falcon.HTTP_792,
            title='Internet crashed!',
            description='Catastrophic weather event',
            href='http://example.com/api/inconvenient-truth',
            href_text='Drill, baby drill!',
        )


class ErroredClassResource:
    def on_get(self, req, resp):
        raise Exception('Plain Exception')

    def on_head(self, req, resp):
        raise CustomBaseException('CustomBaseException')

    def on_delete(self, req, resp):
        raise CustomException('CustomException')


@pytest.fixture
def client(asgi, util):
    app = util.create_app(asgi)
    app.add_route('/', ErroredClassResource())
    return testing.TestClient(app)


class TestErrorHandler:
    def test_caught_error(self, client):
        client.app.add_error_handler(Exception, capture_error)

        result = client.simulate_get()
        assert result.text == 'error: Plain Exception'

        result = client.simulate_head()
        assert result.status_code == 723
        assert not result.content

    @pytest.mark.parametrize(
        'get_headers, resp_content_type, resp_start',
        [
            (None, constants.MEDIA_JSON, '{"'),
            ({'accept': constants.MEDIA_JSON}, constants.MEDIA_JSON, '{"'),
            ({'accept': constants.MEDIA_XML}, constants.MEDIA_XML, '<?xml'),
        ],
    )
    def test_uncaught_python_error(
        self, client, get_headers, resp_content_type, resp_start
    ):
        client.app.resp_options.xml_error_serialization = True
        result = client.simulate_get(headers=get_headers)
        assert result.status_code == 500
        assert result.headers['content-type'] == resp_content_type
        assert result.text.startswith(resp_start)

    def test_caught_error_async(self, asgi):
        if not asgi:
            pytest.skip('Test only applies to ASGI')

        app = falcon.asgi.App()
        app.add_route('/', ErroredClassResource())
        app.add_error_handler(Exception, capture_error_async)

        client = testing.TestClient(app)

        result = client.simulate_get()
        assert result.text == 'error: Plain Exception'

        result = client.simulate_head()
        assert result.status_code == 723
        assert not result.content

    def test_uncaught_error(self, client):
        client.app._error_handlers.clear()
        client.app.add_error_handler(CustomException, capture_error)
        with pytest.raises(Exception):
            client.simulate_get()

    def test_uncaught_error_else(self, client):
        client.app._error_handlers.clear()
        with pytest.raises(Exception):
            client.simulate_get()

    def test_converted_error(self, client):
        client.app.add_error_handler(CustomException)

        result = client.simulate_delete()
        assert result.status_code == 792
        assert result.json['title'] == 'Internet crashed!'

    def test_handle_not_defined(self, client):
        with pytest.raises(AttributeError):
            client.app.add_error_handler(CustomBaseException)

    def test_subclass_error(self, client):
        client.app.add_error_handler(CustomBaseException, capture_error)

        result = client.simulate_delete()
        assert result.status_code == 723
        assert result.text == 'error: CustomException'

    def test_error_precedence_duplicate(self, client):
        client.app.add_error_handler(Exception, capture_error)
        client.app.add_error_handler(Exception, handle_error_first)

        result = client.simulate_get()
        assert result.text == 'first error handler'

    def test_error_precedence_subclass(self, client):
        client.app.add_error_handler(Exception, capture_error)
        client.app.add_error_handler(CustomException, handle_error_first)

        result = client.simulate_delete()
        assert result.status_code == 200
        assert result.text == 'first error handler'

        result = client.simulate_get()
        assert result.status_code == 723
        assert result.text == 'error: Plain Exception'

    def test_error_precedence_subclass_order_indifference(self, client):
        client.app.add_error_handler(CustomException, handle_error_first)
        client.app.add_error_handler(Exception, capture_error)

        result = client.simulate_delete()
        assert result.status_code == 200
        assert result.text == 'first error handler'

    @pytest.mark.parametrize(
        'exceptions',
        [
            (Exception, CustomException),
            [Exception, CustomException],
        ],
    )
    def test_handler_multiple_exception_iterable(self, client, exceptions):
        client.app.add_error_handler(exceptions, capture_error)

        result = client.simulate_get()
        assert result.status_code == 723

        result = client.simulate_delete()
        assert result.status_code == 723

    def test_handler_single_exception_iterable(self, client):
        def exception_list_generator():
            yield CustomException

        client.app.add_error_handler(exception_list_generator(), capture_error)

        result = client.simulate_delete()
        assert result.status_code == 723

    @pytest.mark.parametrize(
        'exceptions',
        [
            NotImplemented,
            'Hello, world!',
            frozenset([ZeroDivisionError, int, NotImplementedError]),
            [float, float],
        ],
    )
    def test_invalid_add_exception_handler_input(self, client, exceptions):
        with pytest.raises(TypeError):
            client.app.add_error_handler(exceptions, capture_error)

    def test_handler_signature_shim(self, util):
        def check_args(ex, req, resp):
            assert isinstance(ex, BaseException)
            assert isinstance(req, falcon.Request)
            assert isinstance(resp, falcon.Response)

        def legacy_handler1(ex, req, resp, params):
            check_args(ex, req, resp)

        def legacy_handler2(error_obj, request, response, params):
            check_args(error_obj, request, response)

        def legacy_handler3(err, rq, rs, prms):
            check_args(err, rq, rs)

        app = util.create_app(asgi=False)
        app.add_route('/', ErroredClassResource())
        client = testing.TestClient(app)

        with pytest.warns(DeprecatedWarning, match='deprecated signature'):
            client.app.add_error_handler(Exception, legacy_handler1)
        with pytest.warns(DeprecatedWarning, match='deprecated signature'):
            client.app.add_error_handler(CustomBaseException, legacy_handler2)
        with pytest.warns(DeprecatedWarning, match='deprecated signature'):
            client.app.add_error_handler(CustomException, legacy_handler3)

        client.simulate_delete()
        client.simulate_get()
        client.simulate_head()

    def test_handler_must_be_coroutine_for_asgi(self, util):
        app = util.create_app(True)

        with util.disable_asgi_non_coroutine_wrapping():
            with pytest.raises(ValueError):
                app.add_error_handler(Exception, capture_error)

    def test_catch_http_no_route_error(self, asgi, util):
        class Resource:
            def on_get(self, req, resp):
                raise falcon.HTTPNotFound()

        def capture_error(req, resp, ex, params):
            resp.set_header('X-name', ex.__class__.__name__)
            raise ex

        app = util.create_app(asgi)
        app.add_route('/', Resource())
        app.add_error_handler(falcon.HTTPError, capture_error)

        client = testing.TestClient(app)

        result = client.simulate_get('/')
        assert result.status_code == 404
        assert result.headers['X-name'] == 'HTTPNotFound'

        result = client.simulate_get('/404')
        assert result.status_code == 404
        assert result.headers['X-name'] == 'HTTPRouteNotFound'


class NoBodyResource:
    def on_get(self, req, res):
        res.data = b'foo'
        raise falcon.HTTPError(falcon.HTTP_IM_A_TEAPOT)

    def on_post(self, req, res):
        res.media = {'a': 1}
        raise falcon.HTTPError(falcon.HTTP_740)

    def on_put(self, req, res):
        res.text = 'foo'
        raise falcon.HTTPError(falcon.HTTP_701)


class TestNoBodyWithStatus:
    @pytest.fixture()
    def body_client(self, asgi, util):
        app = util.create_app(asgi=asgi)
        app.add_route('/error', NoBodyResource())

        def no_reps(req, resp, exception):
            pass

        app.set_error_serializer(no_reps)
        return testing.TestClient(app)

    def test_data_is_set(self, body_client):
        res = body_client.simulate_get('/error')
        assert res.status == falcon.HTTP_IM_A_TEAPOT
        assert res.status_code == 418
        assert res.content == b''

    def test_media_is_set(self, body_client):
        res = body_client.simulate_post('/error')
        assert res.status == falcon.HTTP_740
        assert res.content == b''

    def test_body_is_set(self, body_client):
        res = body_client.simulate_put('/error')
        assert res.status == falcon.HTTP_701
        assert res.content == b''


class _UnserializableMediaResource:
    def on_get(self, req, resp):
        resp.media = object()


class _UnserializableMediaResourceAsync:
    async def on_get(self, req, resp):
        resp.media = object()


class _RaiseNotFoundResource:
    def on_get(self, req, resp):
        raise falcon.HTTPNotFound()


class _RaiseNotFoundResourceAsync:
    async def on_get(self, req, resp):
        raise falcon.HTTPNotFound()


class _OkResource:
    def on_get(self, req, resp):
        resp.text = 'ok'


class _OkResourceAsync:
    async def on_get(self, req, resp):
        resp.text = 'ok'


class _RaiseInResponseMiddleware:
    def process_response(self, req, resp, resource, req_succeeded):
        raise RuntimeError('response middleware failed')

    async def process_response_async(self, req, resp, resource, req_succeeded):
        self.process_response(req, resp, resource, req_succeeded)


class TestErrorResponseLifecycle:
    def _make_client(self, asgi, util, resource, **kwargs):
        app = util.create_app(asgi, **kwargs)
        app.add_route('/', resource)
        return testing.TestClient(app)

    def test_body_rerendered_after_render_failure(self, asgi, util):
        # NOTE: The response has not started yet when the body is rendered, so
        #   a rendering failure must result in the complete error response
        #   instead of an empty 500 with no body.
        resource = (
            _UnserializableMediaResourceAsync()
            if asgi
            else _UnserializableMediaResource()
        )
        client = self._make_client(asgi, util, resource)

        result = client.simulate_get('/')
        assert result.status_code == 500
        assert result.headers['content-type'] == constants.MEDIA_JSON
        assert result.json['title'] == '500 Internal Server Error'

    def test_error_handler_called_once_after_render_failure(self, asgi, util):
        calls = []

        def handle_type_error(req, resp, ex, params):
            calls.append(type(ex))
            resp.status = falcon.HTTP_500
            resp.text = 'render error handled'

        resource = (
            _UnserializableMediaResourceAsync()
            if asgi
            else _UnserializableMediaResource()
        )
        client = self._make_client(asgi, util, resource)
        client.app.add_error_handler(TypeError, handle_type_error)

        result = client.simulate_get('/')
        assert result.status_code == 500
        assert result.text == 'render error handled'
        assert calls == [TypeError]

    def test_faulty_error_serializer_is_separated(self, asgi, util):
        # NOTE: A failure while serializing the error response is propagated
        #   as-is (instead of feeding it back to the error handler), so that
        #   it is not confused with the original exception.
        def faulty_serializer(req, resp, ex):
            resp.content_type = falcon.MEDIA_TEXT
            resp.text = f'{0 / 0}'

        resource = _RaiseNotFoundResourceAsync() if asgi else _RaiseNotFoundResource()
        client = self._make_client(asgi, util, resource)
        client.app.set_error_serializer(faulty_serializer)

        with pytest.raises(ZeroDivisionError):
            client.simulate_get('/')

    def test_body_render_failure_unhandled_propagates(self, asgi, util):
        # NOTE: No response has been started yet, and there is no handler to
        #   compose an alternative one, so the rendering error surfaces as-is.
        resource = (
            _UnserializableMediaResourceAsync()
            if asgi
            else _UnserializableMediaResource()
        )
        client = self._make_client(asgi, util, resource)
        client.app._error_handlers.clear()

        with pytest.raises(TypeError):
            client.simulate_get('/')

    def test_body_render_failure_after_committed_error_propagates(self, asgi, util):
        # NOTE: Once an error response has been committed, a failure while
        #   rendering it is propagated instead of invoking the error handler a
        #   second time (and without emitting a partial response).
        def handle_runtime_error(req, resp, ex, params):
            resp.status = falcon.HTTP_400
            resp.media = object()

        resource = _OkResourceAsync() if asgi else _OkResource()
        app = util.create_app(asgi, middleware=[_RaiseInResponseMiddleware()])
        app.add_error_handler(RuntimeError, handle_runtime_error)
        app.add_route('/', resource)
        client = testing.TestClient(app)

        with pytest.raises(TypeError):
            client.simulate_get('/')


class CustomErrorResource:
    def on_get(self, req, res):
        res.data = b'foo'
        raise ZeroDivisionError()

    def on_post(self, req, res):
        res.media = {'a': 1}
        raise ZeroDivisionError()

    def on_put(self, req, res):
        res.text = 'foo'
        raise ZeroDivisionError()


class TestCustomError:
    @pytest.fixture()
    def body_client(self, asgi, util):
        app = util.create_app(asgi=asgi)
        app.add_route('/error', CustomErrorResource())

        if asgi:

            async def handle_zero_division(req, resp, ex, params):
                assert await resp.render_body() is None
                resp.status = falcon.HTTP_719

        else:

            def handle_zero_division(req, resp, ex, params):  # type: ignore[misc]
                assert resp.render_body() is None
                resp.status = falcon.HTTP_719

        app.add_error_handler(ZeroDivisionError, handle_zero_division)
        return testing.TestClient(app)

    def test_data_is_set(self, body_client):
        res = body_client.simulate_get('/error')
        assert res.status == falcon.HTTP_719
        assert res.content == b''

    def test_media_is_set(self, body_client):
        res = body_client.simulate_post('/error')
        assert res.status == falcon.HTTP_719
        assert res.content == b''

    def test_body_is_set(self, body_client):
        res = body_client.simulate_put('/error')
        assert res.status == falcon.HTTP_719
        assert res.content == b''
