import unittest
from unittest.mock import patch

from app import APP_PORT, app


class LocalHostSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.host = f"127.0.0.1:{APP_PORT}"
        self.origin = f"http://127.0.0.1:{APP_PORT}"

    def test_foreign_host_cannot_read_health_paths(self):
        response = self.client.get("/api/health", headers={"Host": "attacker.example"})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn(b"user_data_dir", response.data)

    def test_cross_origin_post_is_rejected_before_route_work(self):
        response = self.client.post(
            "/api/upload",
            headers={"Host": self.host, "Origin": "https://attacker.example"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"Cross-origin", response.data)

    def test_same_origin_and_originless_local_clients_are_allowed(self):
        with patch("app._discover_ollama_models", return_value=([], None)):
            same_origin = self.client.get(
                "/api/health",
                base_url=f"http://{self.host}",
                headers={"Origin": self.origin},
            )
        self.assertEqual(same_origin.status_code, 200)

        no_origin = self.client.post("/api/upload", headers={"Host": self.host})
        self.assertEqual(no_origin.status_code, 400)  # Route reached; video is missing.
        self.assertIn(b"Choose a video", no_origin.data)

    def test_mismatched_loopback_origin_is_rejected(self):
        response = self.client.post(
            "/api/upload",
            headers={"Host": self.host, "Origin": f"http://localhost:{APP_PORT}"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
