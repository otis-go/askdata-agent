import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.security import AuthService


class AuthServiceTest(unittest.TestCase):
    def test_mock_accounts_issue_isolated_users(self) -> None:
        auth = AuthService()
        admin = auth.login("admin", "admin123")
        sales = auth.login("sales", "sales123")

        self.assertEqual(admin[1].user_id, "demo_admin")
        self.assertEqual(sales[1].user_id, "demo_current_sales")
        self.assertNotEqual(admin[0], sales[0])
        self.assertIsNone(auth.login("admin", "wrong"))

    def test_api_requires_login_and_filters_schema(self) -> None:
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/schema").status_code, 401)
            admin_token = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "admin123"},
            ).json()["access_token"]
            sales_token = client.post(
                "/api/auth/login",
                json={"username": "sales", "password": "sales123"},
            ).json()["access_token"]
            admin_schema = client.get(
                "/api/schema",
                headers={"Authorization": f"Bearer {admin_token}"},
            ).json()
            sales_schema = client.get(
                "/api/schema",
                headers={"Authorization": f"Bearer {sales_token}"},
            ).json()

            self.assertGreater(len(admin_schema), len(sales_schema))
            self.assertNotIn("orders_history", {item["id"] for item in sales_schema})


if __name__ == "__main__":
    unittest.main()
