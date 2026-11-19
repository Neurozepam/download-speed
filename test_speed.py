import contextlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import sys
from threading import Lock, Thread
import time
import unittest

from speed import measure


@contextlib.contextmanager
def server():
    state = {"requests": 0, "active": 0, "max_active": 0}
    lock = Lock()
    payload = b"x" * (130 * 1024)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            with lock:
                state["requests"] += 1
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            try:
                if self.path == "/error":
                    self.send_error(503)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload) + (self.path == "/truncated")))
                self.end_headers()
                self.wfile.write(payload[:1024])
                self.wfile.flush()
                time.sleep(0.01)
                self.wfile.write(payload[1024:])
                self.wfile.flush()
            finally:
                with lock:
                    state["active"] -= 1

        def log_message(self, *_):
            pass

    instance = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}", state, payload
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join()


class SpeedTests(unittest.TestCase):
    def test_cli_prints_measured_bytes_and_units(self):
        with server() as (url, state, payload):
            run = subprocess.run([sys.executable, "speed.py", url], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(state["requests"], 10)
            self.assertIn(f"Downloaded: {len(payload) * 10} bytes", run.stdout)
            self.assertIn("MiB/s", run.stdout)
            self.assertIn("Mbit/s", run.stdout)

    def test_rejects_a_response_cut_short(self):
        with server() as (url, state, _):
            with self.assertRaisesRegex(OSError, "incomplete response"):
                measure(url + "/truncated")
            self.assertEqual(state["requests"], 1)

    def test_reads_ten_complete_responses_sequentially(self):
        with server() as (url, state, payload):
            result = measure(url)
            self.assertEqual(state["requests"], 10)
            self.assertEqual(state["max_active"], 1)
            self.assertEqual(result.total_bytes, 10 * len(payload))
            self.assertGreaterEqual(result.total_seconds, 0.1)
            self.assertAlmostEqual(result.average_seconds, result.total_seconds / 10)
            self.assertAlmostEqual(result.bytes_per_second, result.total_bytes / result.total_seconds)

    def test_cli_reports_http_failure_without_misleading_speed(self):
        with server() as (url, state, _):
            run = subprocess.run([sys.executable, "speed.py", url + "/error"],
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 1)
            self.assertIn("503", run.stderr)
            self.assertEqual(run.stdout, "")
            self.assertEqual(state["requests"], 1)

    def test_cli_rejects_invalid_input_before_network_request(self):
        for arguments in [["file:///etc/hosts"], ["https://example.com", "--timeout", "nan"]]:
            with self.subTest(arguments=arguments):
                run = subprocess.run([sys.executable, "speed.py", *arguments],
                                     capture_output=True, text=True, timeout=10)
                self.assertEqual(run.returncode, 2)
                self.assertEqual(run.stdout, "")


if __name__ == "__main__":
    unittest.main()
