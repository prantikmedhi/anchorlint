"""Offline provider-contract tests; all responses/keys are explicit fixtures.

Actual TDD checkpoints from development (not live API results):
  Initial RED: Ran 1 test; FAILED (failures=1), adapter absent.
  Scalar-validation RED: Ran 3 tests; FAILED (failures=40, errors=8).
  Scalar-validation GREEN: Ran 3 tests in 0.026s; OK.
  Full pre-refactor GREEN: Ran 16 tests in 0.065s; OK.
"""

import importlib
from http.client import IncompleteRead
from email.message import Message
from email.utils import formatdate
import io
import json
import math
from pathlib import Path
import unittest
import traceback
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.response import addinfourl


KEY = "fixture-only-key-not-a-credential"
ENDPOINT = "https://api.typesafe.ai/v1/systemone"
LABELS = {"informative", "generic", "misleading", "insufficient_context"}
INPUTS = ("Install guide", "Read the Install guide.", "Installation", "Install using pip.")


def response_fixture():
    """Documented API shape, not a real Jev result or accuracy claim."""
    return {
        "model": "jev-1.13.0",
        "answers": {
            "promise": {"type": "noul", "noul": 0.91},
            "relevance": {"type": "noul", "noul": 0.82},
            "label": {
                "type": "choice",
                "choice": "informative",
                "confidence": 0.73,
                "probabilities": {
                    "informative": 0.8,
                    "generic": 0.1,
                    "misleading": 0.05,
                    "insufficient_context": 0.05,
                },
            },
        },
        "usage": {"input_tokens": 301, "output_tokens": 42},
    }


class FixtureResponse(io.BytesIO):
    status = 200
    headers = {}

    def geturl(self):
        return ENDPOINT


class FixtureTransport:
    def __init__(self, payload=None):
        self.payload = response_fixture() if payload is None else payload
        self.requests = []

    def __call__(self, request, *, timeout):
        self.requests.append((request, timeout))
        return FixtureResponse(json.dumps(self.payload).encode("utf-8"))


class RawTransport:
    def __init__(self, body):
        self.response = FixtureResponse(body)
        self.calls = 0

    def __call__(self, request, *, timeout):
        self.calls += 1
        return self.response


class SequenceTransport:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []

    def __call__(self, request, *, timeout):
        self.requests.append((request, timeout))
        if not self.steps:
            raise AssertionError("Unexpected extra provider call")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def http_error(status, retry_after=None):
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError(ENDPOINT, status, "sensitive " + KEY, headers, io.BytesIO(KEY.encode()))


class JevTests(unittest.TestCase):
    def setUp(self):
        # Nested fixture patches opt in only to explicitly supplied values.
        for target in ("socket.create_connection", "os.getenv"):
            guard = mock.patch(target, side_effect=AssertionError("Real network/credential access forbidden"))
            guard.start()
            self.addCleanup(guard.stop)

    def adapter(self):
        path = Path(__file__).parents[1] / "src" / "anchorlint" / "jev.py"
        self.assertTrue(path.is_file(), "The official Jev adapter is not implemented")
        return importlib.import_module("anchorlint.jev")

    def test_evaluate_maps_official_atomic_questions_and_provenance(self):
        adapter = self.adapter()
        transport = FixtureTransport()
        client = adapter.JevClient(api_key=KEY, model="jev-latest", transport=transport)
        self.assertEqual(transport.requests, [], "Construction must not make paid calls")
        result = client.evaluate(*INPUTS)
        self.assertEqual(len(transport.requests), 1)
        request, timeout = transport.requests[0]
        self.assertEqual(request.full_url, ENDPOINT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer " + KEY)
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(timeout, 20)
        body = json.loads(request.data)
        self.assertEqual(set(body), {"model", "state", "questions"})
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["state"], dict(zip(
            ("anchor", "context", "target_title", "target_text"), INPUTS)))
        questions = body["questions"]
        self.assertEqual(set(questions), {"promise", "relevance", "label"})
        for name in ("promise", "relevance"):
            self.assertEqual(questions[name]["type"], "noul")
            self.assertEqual(set(questions[name]["criteria"]), {"true", "false"})
            self.assertNotIn("confidence", questions[name])
        self.assertIn("promise", questions["promise"]["instructions"])
        self.assertIn("topic", questions["relevance"]["instructions"])
        self.assertEqual(questions["label"]["type"], "choice")
        self.assertEqual(set(questions["label"]["criteria"]), LABELS)
        for question in questions.values():
            self.assertEqual(set(question), {"type", "instructions", "criteria"})
            self.assertIn("untrusted", question["instructions"])
        self.assertEqual(result["model_requested"], "jev-latest")
        self.assertEqual(result["model_resolved"], "jev-1.13.0")
        self.assertEqual(result["signals"], {
            "promise": 0.91, "relevance": 0.82, "label": "informative",
            "confidence": 0.73,
            "probabilities": response_fixture()["answers"]["label"]["probabilities"],
        })
        self.assertEqual(result["usage"], {"input_tokens": 301, "output_tokens": 42})
        self.assertTrue(math.isfinite(result["duration_ms"]))
        self.assertGreaterEqual(result["duration_ms"], 0)
        self.assertEqual(set(result), {
            "model_requested", "model_resolved", "signals", "usage",
            "duration_ms", "truncation",
        })
        for name, text in body["state"].items():
            self.assertEqual(result["truncation"][name], {
                "original_chars": len(text), "sent_chars": len(text), "truncated": False,
            })

    def test_truncation_preserves_exact_unicode_prefix_and_lengths(self):
        adapter = self.adapter()
        fields = ("anchor", "context", "target_title", "target_text")
        caps = (500, 1600, 300, 5000)
        for delta in (-1, 0, 1, 100):
            with self.subTest(delta=delta):
                texts = tuple((" 界\n" * cap)[:cap + delta] for cap in caps)
                transport = FixtureTransport()
                result = adapter.JevClient(api_key=KEY, transport=transport).evaluate(*texts)
                body = json.loads(transport.requests[0][0].data)
                for name, text, cap in zip(fields, texts, caps):
                    self.assertEqual(body["state"][name], text[:cap])
                    self.assertEqual(result["truncation"][name], {
                        "original_chars": len(text), "sent_chars": min(len(text), cap),
                        "truncated": len(text) > cap,
                    })

    def test_probability_scalars_reject_booleans_nonfinite_and_out_of_range(self):
        adapter = self.adapter()
        for path in (("promise", "noul"), ("relevance", "noul"),
                     ("label", "confidence"), ("label", "probabilities", "informative")):
            for bad in (True, False, float("nan"), float("inf"), -float("inf"),
                        -0.01, 1.01, "0.8", None, [], {}, 10 ** 400):
                with self.subTest(path=path, bad=repr(bad)):
                    payload = response_fixture()
                    field = payload["answers"]
                    for name in path[:-1]:
                        field = field[name]
                    field[path[-1]] = bad
                    client = adapter.JevClient(api_key=KEY, transport=FixtureTransport(payload))
                    with self.assertRaises(adapter.JevError) as caught:
                        client.evaluate(*INPUTS)
                    self.assertEqual(str(caught.exception), "Jev returned an invalid response.")

    def assert_invalid_response(self, payload):
        adapter = self.adapter()
        client = adapter.JevClient(api_key=KEY, transport=FixtureTransport(payload))
        try:
            client.evaluate(*INPUTS)
        except Exception as error:
            self.assertIsInstance(error, adapter.JevError)
            self.assertEqual(str(error), "Jev returned an invalid response.")
        else:
            self.fail("Malformed response was accepted")

    def test_required_response_shape_ids_types_model_and_usage_are_validated(self):
        for field in ("model", "answers", "usage"):
            payload = response_fixture()
            del payload[field]
            with self.subTest(missing=field):
                self.assert_invalid_response(payload)
        for payload in ([], 1, True, "body must never leak " + KEY):
            with self.subTest(top_type=type(payload).__name__):
                self.assert_invalid_response(payload)
        for bad in (None, False, 12, [], {}, "", " ", "jev-1.13.0\n", "https://evil.test/", "x" * 200):
            payload = response_fixture()
            payload["model"] = bad
            with self.subTest(model=repr(bad)):
                self.assert_invalid_response(payload)
        for field in ("answers", "usage"):
            for bad in (None, False, [], "bad"):
                payload = response_fixture()
                payload[field] = bad
                with self.subTest(field=field, bad=repr(bad)):
                    self.assert_invalid_response(payload)
        for name in ("promise", "relevance", "label"):
            payload = response_fixture()
            del payload["answers"][name]
            with self.subTest(missing_answer=name):
                self.assert_invalid_response(payload)
            for bad in (None, [], "bad", {"type": "score"}):
                payload = response_fixture()
                payload["answers"][name] = bad
                with self.subTest(answer=name, bad=repr(bad)):
                    self.assert_invalid_response(payload)
            for field in response_fixture()["answers"][name]:
                payload = response_fixture()
                del payload["answers"][name][field]
                with self.subTest(answer=name, missing_field=field):
                    self.assert_invalid_response(payload)
            payload = response_fixture()
            payload["answers"][name]["type"] = "score"
            with self.subTest(wrong_type=name):
                self.assert_invalid_response(payload)
        payload = response_fixture()
        payload["answers"]["unexpected"] = {"type": "noul", "noul": 0.5}
        with self.subTest(unexpected_answer=True):
            self.assert_invalid_response(payload)
        for field in ("input_tokens", "output_tokens"):
            payload = response_fixture()
            del payload["usage"][field]
            with self.subTest(missing_usage=field):
                self.assert_invalid_response(payload)
            for bad in (True, False, -1, 1.0, "301", None, [], float("nan"), float("inf")):
                payload = response_fixture()
                payload["usage"][field] = bad
                with self.subTest(usage=field, bad=repr(bad)):
                    self.assert_invalid_response(payload)

    def test_choice_requires_complete_normalized_distribution_and_maximum_label(self):
        for label in (None, [], {}, True, "unknown", "generic"):
            payload = response_fixture()
            payload["answers"]["label"]["choice"] = label
            with self.subTest(label=repr(label)):
                self.assert_invalid_response(payload)
        for probabilities in (
            {}, {"informative": 1},
            {"informative": 0.8, "generic": 0.1, "misleading": 0.05, "extra": 0.05},
            {"informative": 0.8, "generic": 0.1, "misleading": 0.05, "insufficient_context": 0.05, "extra": 0},
            dict.fromkeys(LABELS, 0), dict.fromkeys(LABELS, 0.5),
            dict.fromkeys(LABELS, 0.249),
        ):
            payload = response_fixture()
            payload["answers"]["label"]["probabilities"] = probabilities
            with self.subTest(probabilities=probabilities):
                self.assert_invalid_response(payload)
        adapter = self.adapter()
        for probabilities in (
            dict.fromkeys(LABELS, 0.25),
            {"informative": 0.9999999, "generic": 0, "misleading": 0, "insufficient_context": 0},
        ):
            payload = response_fixture()
            payload["answers"]["label"]["probabilities"] = probabilities
            result = adapter.JevClient(api_key=KEY, transport=FixtureTransport(payload)).evaluate(*INPUTS)
            self.assertEqual(result["signals"]["probabilities"], probabilities)
            self.assertEqual(result["signals"]["confidence"], 0.73)

    def test_invalid_json_duplicate_keys_and_oversize_body_fail_closed(self):
        adapter = self.adapter()
        valid = json.dumps(response_fixture()).encode()
        bodies = (
            b"not JSON " + KEY.encode(), b"\xff", b"null", b"",
            b'{"model":"jev-1.13.0",' + valid[1:],
            valid.replace(b'"noul": 0.91', b'"noul": 0.2, "noul": 0.91'),
            valid[:-1] + b', "unused": NaN}',
            b"[" * 1500 + b"0" + b"]" * 1500,
            valid + b" " * 65536,
        )
        for body in bodies:
            with self.subTest(body_prefix=repr(body[:35])):
                transport = RawTransport(body)
                client = adapter.JevClient(api_key=KEY, transport=transport)
                try:
                    client.evaluate(*INPUTS)
                except Exception as error:
                    self.assertIsInstance(error, adapter.JevError)
                    self.assertNotIn(KEY, str(error))
                    self.assertIn("response", str(error))
                else:
                    self.fail("Invalid or oversized JSON response was accepted")
                self.assertEqual(transport.calls, 1)
                self.assertTrue(transport.response.closed)

    def test_credentials_use_only_explicit_key_or_named_environment_value(self):
        adapter = self.adapter()
        with mock.patch("os.getenv", return_value=KEY) as getenv:
            transport = FixtureTransport()
            try:
                adapter.JevClient(transport=transport).evaluate(*INPUTS)
            except Exception as error:
                self.fail("Explicit fixture environment key was not supported: " + type(error).__name__)
            getenv.assert_called_once_with("TYPESAFE_API_KEY")
            self.assertEqual(transport.requests[0][0].get_header("Authorization"), "Bearer " + KEY)
        with mock.patch("os.getenv", side_effect=AssertionError("Unexpected environment read")):
            adapter.JevClient(api_key=KEY, transport=FixtureTransport()).evaluate(*INPUTS)
        for bad in ("", " ", "bad\r\nInjected: value", "non-ascii-界", 123, True):
            with self.subTest(key_type=type(bad).__name__):
                transport = FixtureTransport()
                with mock.patch("os.getenv", side_effect=AssertionError("Unexpected environment read")):
                    try:
                        adapter.JevClient(api_key=bad, transport=transport).evaluate(*INPUTS)
                    except Exception as error:
                        self.assertIsInstance(error, adapter.JevError)
                        self.assertNotIn("Injected", str(error))
                    else:
                        self.fail("Invalid explicit key was accepted")
                self.assertEqual(transport.requests, [])
        with mock.patch("os.getenv", return_value=None):
            with self.assertRaises(adapter.JevError) as caught:
                adapter.JevClient(transport=FixtureTransport()).evaluate(*INPUTS)
            self.assertIn("TYPESAFE_API_KEY", str(caught.exception))

    def test_configuration_and_text_types_fail_before_transport(self):
        adapter = self.adapter()
        for field, values in {
            "timeout": (None, True, 0, -1, float("nan"), float("inf"), 61, "20", 10 ** 400),
            "max_retries": (None, True, -1, 4, 1.0, "2"),
            "model": (None, True, "", " ", "jev-1.13.0\n", "https://evil.test/", "x" * 200),
        }.items():
            for bad in values:
                with self.subTest(field=field, bad=repr(bad)):
                    transport = FixtureTransport()
                    with self.assertRaises(adapter.JevError):
                        adapter.JevClient(api_key=KEY, transport=transport, **{field: bad})
                    self.assertEqual(transport.requests, [])
        for index in range(4):
            for bad in (None, True, 42, [], {}, b"bytes"):
                with self.subTest(input_index=index, bad=repr(bad)):
                    texts = list(INPUTS)
                    texts[index] = bad
                    transport = FixtureTransport()
                    try:
                        adapter.JevClient(api_key=KEY, transport=transport).evaluate(*texts)
                    except Exception as error:
                        self.assertIsInstance(error, adapter.JevError)
                    else:
                        self.fail("Non-text input was accepted")
                    self.assertEqual(transport.requests, [])

    def test_default_urllib_transport_cannot_follow_redirects_or_use_global_opener(self):
        adapter = self.adapter()
        for status in (200, 301, 302, 303, 307, 308):
            for location in ("https://evil.test/collect", ENDPOINT + "/moved"):
                with self.subTest(status=status, location=location):
                    seen = []
                    streams = []

                    class FixtureHTTPSHandler(adapter.urlrequest.HTTPSHandler):
                        def https_open(self, request):
                            seen.append(request)
                            headers = Message()
                            headers["Location"] = location
                            stream = io.BytesIO(json.dumps(response_fixture()).encode())
                            streams.append(stream)
                            response = addinfourl(stream, headers, request.full_url, status)
                            response.msg = "fixture"
                            return response

                    with mock.patch.object(adapter.urlrequest, "HTTPSHandler", FixtureHTTPSHandler), \
                            mock.patch.object(adapter.urlrequest, "urlopen", side_effect=AssertionError("Global opener forbidden")):
                        client = adapter.JevClient(api_key=KEY)
                        self.assertEqual(seen, [])
                        try:
                            result = client.evaluate(*INPUTS)
                        except Exception as error:
                            self.assertNotEqual(status, 200, "Default transport did not use isolated urllib opener")
                            self.assertIsInstance(error, adapter.JevError)
                            self.assertNotIn(KEY, str(error))
                        else:
                            self.assertEqual(status, 200, "Redirect was treated as successful evaluation")
                            self.assertEqual(result["model_resolved"], "jev-1.13.0")
                    self.assertEqual(len(seen), 1)
                    self.assertEqual(seen[0].full_url, ENDPOINT)
                    self.assertEqual(seen[0].get_header("Authorization"), "Bearer " + KEY)
                    self.assertTrue(all(stream.closed for stream in streams))

    def test_transient_http_errors_retry_with_bounded_exponential_backoff(self):
        adapter = self.adapter()
        for status in (429, 500, 502, 503, 504, 529, 599):
            with self.subTest(status=status):
                errors = [http_error(status), http_error(status)]
                transport = SequenceTransport(*errors, FixtureResponse(json.dumps(response_fixture()).encode()))
                sleeps = []
                try:
                    result = adapter.JevClient(api_key=KEY, transport=transport, sleep=sleeps.append).evaluate(*INPUTS)
                except Exception as error:
                    self.fail("Transient HTTP failure was not retried: " + type(error).__name__)
                self.assertEqual(result["model_resolved"], "jev-1.13.0")
                self.assertEqual(len(transport.requests), 3)
                self.assertEqual(sleeps, [1, 2])
                self.assertTrue(all(error.closed for error in errors))
                self.assertEqual(len({request.data for request, _ in transport.requests}), 1)
        for retries in (0, 1, 2, 3):
            with self.subTest(exhausted_retries=retries):
                errors = [http_error(529) for _ in range(retries + 1)]
                transport = SequenceTransport(*errors)
                sleeps = []
                with self.assertRaises(adapter.JevError):
                    adapter.JevClient(api_key=KEY, max_retries=retries,
                                      transport=transport, sleep=sleeps.append).evaluate(*INPUTS)
                self.assertEqual(len(transport.requests), retries + 1)
                self.assertEqual(len(sleeps), retries)
                self.assertTrue(all(error.closed for error in errors))

    def test_retry_after_is_honored_without_retrying_early_on_long_delays(self):
        adapter = self.adapter()
        for header, delay in (("7", 7), ("1.5", 1.5), ("0", 1),
                              (formatdate(1700000007, usegmt=True), 7),
                              ("garbage", 1), ("-2", 1), ("NaN", 1), ("Infinity", 1)):
            with self.subTest(header=header):
                transport = SequenceTransport(http_error(429, header),
                                              FixtureResponse(json.dumps(response_fixture()).encode()))
                sleeps = []
                with mock.patch.object(adapter.time, "time", return_value=1700000000):
                    adapter.JevClient(api_key=KEY, transport=transport, sleep=sleeps.append).evaluate(*INPUTS)
                self.assertEqual(sleeps, [delay])
                self.assertEqual(len(transport.requests), 2)
        for header in ("11", "999999999999999999999999", "9" * 400, formatdate(1700003600, usegmt=True)):
            with self.subTest(excessive_retry_after=header):
                transport = SequenceTransport(http_error(503, header))
                sleeps = []
                with mock.patch.object(adapter.time, "time", return_value=1700000000):
                    try:
                        adapter.JevClient(api_key=KEY, transport=transport, sleep=sleeps.append).evaluate(*INPUTS)
                    except Exception as error:
                        self.assertIsInstance(error, adapter.JevError)
                        self.assertIn("retry", str(error).lower())
                    else:
                        self.fail("Excessive Retry-After was not bounded")
                self.assertEqual(sleeps, [])
                self.assertEqual(len(transport.requests), 1)

    def test_total_budget_limits_retries_timeouts_and_late_success(self):
        adapter = self.adapter()
        for scenario in ("remaining_timeout", "delay_too_long", "late_response", "oversleep"):
            with self.subTest(scenario=scenario):
                now = [1000.0]
                calls = []
                sleeps = []

                def transport(request, *, timeout):
                    calls.append(timeout)
                    if scenario == "late_response":
                        now[0] += 91
                    elif len(calls) == 1:
                        now[0] += 89 if scenario == "delay_too_long" else 60
                        raise http_error(503, "5" if scenario == "delay_too_long" else None)
                    else:
                        now[0] += 1
                    return FixtureResponse(json.dumps(response_fixture()).encode())

                def sleep(delay):
                    sleeps.append(delay)
                    now[0] += 100 if scenario == "oversleep" else delay

                with mock.patch.object(adapter.time, "monotonic", side_effect=lambda: now[0]):
                    client = adapter.JevClient(api_key=KEY, timeout=60, transport=transport, sleep=sleep)
                    if scenario == "remaining_timeout":
                        result = client.evaluate(*INPUTS)
                        self.assertEqual(calls, [60, 29])
                        self.assertEqual(result["duration_ms"], 62000)
                    else:
                        with self.assertRaises(adapter.JevError):
                            client.evaluate(*INPUTS)
                        self.assertEqual(len(calls), 1)
                        if scenario != "oversleep":
                            self.assertEqual(sleeps, [])

    def test_failures_are_sanitized_without_retrying_auth_or_ambiguous_network_errors(self):
        adapter = self.adapter()
        for failure in (TimeoutError(KEY), URLError(KEY), OSError(KEY),
                        IncompleteRead(KEY.encode()), http_error(401), http_error(403),
                        http_error(400), http_error(404), http_error(422)):
            with self.subTest(failure_type=type(failure).__name__, status=getattr(failure, "code", None)):
                sleeps = []
                transport = SequenceTransport(failure)
                try:
                    adapter.JevClient(api_key=KEY, transport=transport, sleep=sleeps.append).evaluate(*INPUTS)
                except Exception as error:
                    self.assertIsInstance(error, adapter.JevError)
                    self.assertNotIn(KEY, str(error))
                    self.assertNotIn(KEY, "".join(traceback.format_exception(error)))
                else:
                    self.fail("Provider failure was converted into success")
                self.assertEqual(len(transport.requests), 1)
                self.assertEqual(sleeps, [])
                if isinstance(failure, HTTPError):
                    self.assertTrue(failure.closed)

    def test_http_metadata_never_turns_error_or_redirect_body_into_success(self):
        adapter = self.adapter()
        for status, url in ((401, ENDPOINT), (302, ENDPOINT), (204, ENDPOINT),
                            (200, "https://evil.test/"), (True, ENDPOINT), (KEY, ENDPOINT)):
            with self.subTest(status=status, url=url):
                body = FixtureResponse(json.dumps(response_fixture()).encode())
                body.status = status
                body.geturl = lambda: url
                body.read = mock.Mock(side_effect=AssertionError("Error body must not be read"))
                body.read1 = mock.Mock(side_effect=AssertionError("Error body must not be read"))
                transport = SequenceTransport(body)
                try:
                    adapter.JevClient(api_key=KEY, transport=transport).evaluate(*INPUTS)
                except Exception as error:
                    self.assertIsInstance(error, adapter.JevError)
                    self.assertNotIn(KEY, str(error))
                    self.assertNotIn("evil.test", str(error))
                else:
                    self.fail("Unsuccessful HTTP response accepted")
                self.assertTrue(body.closed)
                self.assertEqual(len(transport.requests), 1)
        malformed_status = http_error(KEY)
        with self.assertRaises(adapter.JevError):
            adapter.JevClient(api_key=KEY, transport=SequenceTransport(malformed_status)).evaluate(*INPUTS)
        self.assertTrue(malformed_status.closed)

    def test_response_stream_reads_are_bounded_and_deadline_checked_between_chunks(self):
        adapter = self.adapter()
        for slow in (False, True):
            with self.subTest(slow=slow):
                now = [1000.0]
                sizes = []

                class ChunkedResponse(FixtureResponse):
                    def read(self, size=-1):
                        raise AssertionError("Use one bounded socket read, not a fill-to-size read")

                    def read1(self, size=-1):
                        sizes.append(size)
                        if slow:
                            now[0] += 40
                            return b" "
                        return super().read1(size)

                response = ChunkedResponse(json.dumps(response_fixture()).encode())
                with mock.patch.object(adapter.time, "monotonic", side_effect=lambda: now[0]):
                    client = adapter.JevClient(api_key=KEY, transport=SequenceTransport(response))
                    try:
                        result = client.evaluate(*INPUTS)
                    except Exception as error:
                        self.assertTrue(slow, "Normal response did not use bounded streaming")
                        self.assertIsInstance(error, adapter.JevError)
                        self.assertIn("time", str(error))
                    else:
                        self.assertFalse(slow, "A trickling response evaded the deadline")
                        self.assertEqual(result["model_resolved"], "jev-1.13.0")
                self.assertTrue(response.closed)
                self.assertTrue(sizes)
                self.assertTrue(all(0 < size <= 8192 for size in sizes))
                if slow:
                    self.assertLessEqual(len(sizes), 3)

    def test_success_returns_only_typed_contract_fields_not_server_extras(self):
        adapter = self.adapter()
        for label in LABELS:
            with self.subTest(label=label):
                payload = response_fixture()
                payload["model"] = "jev-1.14.0"
                payload["raw_reasoning"] = KEY
                payload["answers"]["promise"].update(noul=0, confidence=KEY)
                payload["answers"]["relevance"]["noul"] = 1
                payload["answers"]["label"].update(
                    choice=label, confidence=1,
                    probabilities={option: int(option == label) for option in LABELS})
                payload["usage"] = {"input_tokens": 0, "output_tokens": 0, "raw_debug": KEY}
                transport = FixtureTransport(payload)
                result = adapter.JevClient(api_key=KEY, model="jev-latest", transport=transport).evaluate(*INPUTS)
                self.assertEqual(result["model_requested"], "jev-latest")
                self.assertEqual(result["model_resolved"], "jev-1.14.0")
                self.assertEqual(result["usage"], {"input_tokens": 0, "output_tokens": 0})
                self.assertNotIn(KEY, json.dumps(result))
                self.assertEqual(result["signals"]["label"], label)
                for name in ("promise", "relevance", "confidence"):
                    self.assertIs(type(result["signals"][name]), float)
                for probability in result["signals"]["probabilities"].values():
                    self.assertIs(type(probability), float)


if __name__ == "__main__":
    unittest.main()
