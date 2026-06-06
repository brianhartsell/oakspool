"""API client for Leslie's Pool water tests."""

import json
import logging
import requests
from bs4 import BeautifulSoup, Tag

_LOG = logging.getLogger(__name__)


class LesliesPoolApi:
    LOGIN_PAGE_URL = "https://lesliespool.com/on/demandware.store/Sites-lpm_site-Site/en_US/Account-Show"
    LOGIN_URL = "https://lesliespool.com/on/demandware.store/Sites-lpm_site-Site/en_US/Account-Login"
    WATER_TEST_URL = "https://lesliespool.com/on/demandware.store/Sites-lpm_site-Site/en_US/WaterTest-GetWaterTest"

    BROWSER_HEADERS = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.5",
        "accept-encoding": "gzip, deflate, br",
        "connection": "keep-alive",
        "upgrade-insecure-requests": "1",
    }

    def __init__(self, username, password, pool_profile_id, pool_name):
        self.username = username
        self.password = password
        self.pool_profile_id = pool_profile_id
        self.pool_name = pool_name
        self.session = requests.Session()

    def authenticate(self):
        resp = self.session.get(self.LOGIN_PAGE_URL, headers=self.BROWSER_HEADERS)
        if resp.status_code != 200:
            _LOG.error("Login page HTTP %s", resp.status_code)
            return False

        soup = BeautifulSoup(resp.text, "html.parser")
        csrf_tag = soup.find("input", {"name": "csrf_token"})
        if not isinstance(csrf_tag, Tag) or not csrf_tag.has_attr("value"):
            _LOG.error("CSRF token not found (HTTP %s). Snippet: %s", resp.status_code, resp.text[:300])
            return False

        login_resp = self.session.post(
            self.LOGIN_URL,
            headers={
                **self.BROWSER_HEADERS,
                "accept": "application/json, text/javascript, */*; q=0.01",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "referer": self.LOGIN_PAGE_URL,
                "origin": "https://lesliespool.com",
            },
            data={
                "loginEmail": self.username,
                "loginPassword": self.password,
                "csrf_token": csrf_tag["value"],
            },
        )
        if login_resp.status_code != 200:
            _LOG.error("Login POST HTTP %s", login_resp.status_code)
            return False
        return True

    def fetch_water_test_data(self):
        data = {}
        for attempt in range(1, 3):
            try:
                if attempt > 1 and not self.authenticate():
                    return {}

                landing = self.session.get(
                    f"https://lesliespool.com/on/demandware.store/Sites-lpm_site-Site/en_US/WaterTest-Landing"
                    f"?poolProfileId={self.pool_profile_id}&poolName={self.pool_name}",
                    headers=self.BROWSER_HEADERS,
                )
                if "Account-Show" in landing.url or "login?rurl=1" in landing.url:
                    if attempt < 2:
                        continue
                    return {}

                cookies = "; ".join(f"{k}={v}" for k, v in self.session.cookies.get_dict().items())
                resp = self.session.post(
                    self.WATER_TEST_URL,
                    headers={
                        **self.BROWSER_HEADERS,
                        "accept": "application/json, text/javascript, */*; q=0.01",
                        "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "referer": (
                            f"https://lesliespool.com/on/demandware.store/Sites-lpm_site-Site/en_US/"
                            f"WaterTest-Landing?poolProfileId={self.pool_profile_id}&poolName={self.pool_name}"
                        ),
                        "origin": "https://lesliespool.com",
                        "cookie": cookies,
                    },
                    data="poolProfileName=Pool&poolSanitizer=Salt+3000-4000",
                )

                if resp.status_code != 200:
                    if attempt < 2:
                        continue
                    return {}

                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    if "<html" in resp.text[:100].lower() and attempt < 2:
                        if self.authenticate():
                            continue
                    return {}

                if "errorMsg" in data and "login" in str(data.get("errorMsg")).lower() and attempt < 2:
                    if self.authenticate():
                        continue
                break

            except requests.RequestException as exc:
                _LOG.error("Request failed: %s", exc)
                if attempt < 2:
                    continue
                return {}

        if "response" not in data:
            return {}

        soup = BeautifulSoup(data["response"], "html.parser")
        table = soup.find("table", {"class": "table table-striped table-bordered table-hover table-sm"})
        if not isinstance(table, Tag):
            return {}

        tbody = table.find("tbody")
        if not isinstance(tbody, Tag):
            return {}

        first_row = tbody.find("tr")
        if not isinstance(first_row, Tag):
            return {}

        columns = first_row.find_all("td")
        if len(columns) <= 10:
            return {}

        test_date = None
        date_tag = first_row.find("th", {"class": "text-center align-middle p-1"})
        if date_tag:
            badge = date_tag.find("span", {"class": "badge badge-secondary p-2"})
            if badge:
                test_date = badge.text.strip()

        in_store_tag = first_row.find_all("td")[-1]
        in_store = not bool(
            in_store_tag and in_store_tag.find("i", {"class": "fa fa-times-circle text-danger"})
        )

        return {
            "free_chlorine": columns[1].text.strip(),
            "total_chlorine": columns[2].text.strip(),
            "ph": columns[3].text.strip(),
            "alkalinity": columns[4].text.strip(),
            "calcium": columns[5].text.strip(),
            "cyanuric_acid": columns[6].text.strip(),
            "iron": columns[7].text.strip(),
            "copper": columns[8].text.strip(),
            "phosphates": columns[9].text.strip(),
            "salt": columns[10].text.strip(),
            "test_date": test_date,
            "in_store": in_store,
        }
