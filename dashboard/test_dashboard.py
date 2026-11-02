import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from dashboard import server


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        server.load()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join()

    def test_demo_has_six_subjects_and_consistent_links(self):
        data = server.validate(json.loads((server.BASE / "sample-data.json").read_text(encoding="utf-8-sig")))
        self.assertEqual(len(data["subjects"]), 6)
        self.assertEqual(len(data["targets"]), 12)
        self.assertFalse(any(data["locks"].values()))

    def test_release_claim_is_rejected(self):
        data = json.loads(json.dumps(server.DATA))
        data["locks"]["student_release"] = True
        with self.assertRaisesRegex(ValueError, "不得声明"):
            server.validate(data)

    def test_cross_subject_record_is_rejected(self):
        data = json.loads(json.dumps(server.DATA))
        data["records"][0]["target_ids"] = ["DEMO-MA-001"]
        with self.assertRaisesRegex(ValueError, "跨学科"):
            server.validate(data)

    def test_health_html_js_css_and_data_endpoints(self):
        for path, content_type in [
            ("/api/health", "application/json"),
            ("/", "text/html"),
            ("/assets/app.js", "text/javascript"),
            ("/assets/style.css", "text/css"),
            ("/api/dashboard", "application/json"),
        ]:
            with self.subTest(path=path), urllib.request.urlopen(self.url + path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(content_type, response.headers["Content-Type"])
                self.assertGreater(len(response.read()), 10)

    def test_unknown_asset_and_mutation_are_blocked(self):
        for method, path, expected in [("GET", "/../../sample-data.json", 404), ("POST", "/api/dashboard", 405)]:
            with self.subTest(method=method):
                try:
                    urllib.request.urlopen(urllib.request.Request(self.url + path, method=method))
                    self.fail("request should fail")
                except urllib.error.HTTPError as error:
                    self.assertEqual(error.code, expected)


if __name__ == "__main__":
    unittest.main()
