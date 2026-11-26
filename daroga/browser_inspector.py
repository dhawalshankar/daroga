"""
DAROGA Browser Automation & Console Inspection Module (Playwright / CDP)
========================================================================
Inspects the user's ALREADY-OPEN browser session via Chrome DevTools Protocol (CDP).
Strictly read-only: never extracts cookies, passwords, or session tokens.
Does NOT launch a new browser or disrupt the user's active session.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import urllib.request
import json

logger = logging.getLogger("daroga.browser_inspector")


@dataclass
class BrowserConsoleFinding:
    cdp_available: bool = False
    cdp_url: str = "http://127.0.0.1:9222"
    open_tabs: List[Dict[str, str]] = field(default_factory=list)
    aws_console_tabs: List[Dict[str, str]] = field(default_factory=list)
    detected_account_or_user: Optional[str] = None
    detected_region: Optional[str] = None
    active_service_page: Optional[str] = None
    notes: List[str] = field(default_factory=list)


class BrowserInspector:
    """
    Connects to an existing Chrome browser via CDP on port 9222.
    """

    def __init__(self, cdp_url: str = "http://127.0.0.1:9222"):
        self.cdp_url = cdp_url.rstrip("/")

    def is_cdp_reachable(self) -> bool:
        """Quick probe to check if CDP port is open before initializing Playwright."""
        try:
            req = urllib.request.Request(f"{self.cdp_url}/json/version", headers={"User-Agent": "DAROGA-Auditor"})
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def inspect(self) -> BrowserConsoleFinding:
        finding = BrowserConsoleFinding(cdp_url=self.cdp_url)

        # 1. Check CDP availability
        if not self.is_cdp_reachable():
            finding.cdp_available = False
            finding.notes.append(
                f"Chrome DevTools Protocol (CDP) is not listening on {self.cdp_url}. "
                "To enable live browser console inspection, launch Chrome with: "
                "`chrome.exe --remote-debugging-port=9222` (preserving your existing user profile)."
            )
            return finding

        finding.cdp_available = True

        # 2. Inspect tabs using CDP /json endpoint
        try:
            req = urllib.request.Request(f"{self.cdp_url}/json/list", headers={"User-Agent": "DAROGA-Auditor"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                tabs_data = json.loads(resp.read().decode("utf-8"))
                for tab in tabs_data:
                    title = tab.get("title", "")
                    url = tab.get("url", "")
                    if tab.get("type") == "page":
                        finding.open_tabs.append({"title": title, "url": url})
                        if "console.aws.amazon.com" in url or "amazonaws.com" in url or "AWS Management Console" in title:
                            finding.aws_console_tabs.append({"title": title, "url": url})
                            
                            # Parse region from AWS console URL (e.g. ?region=us-east-1)
                            if "region=" in url:
                                try:
                                    r_part = url.split("region=")[1].split("&")[0].split("#")[0]
                                    finding.detected_region = r_part
                                except Exception:
                                    pass

                            if "ec2" in url:
                                finding.active_service_page = "Amazon EC2 Console"
                            elif "lambda" in url:
                                finding.active_service_page = "AWS Lambda Console"
                            elif "apigateway" in url:
                                finding.active_service_page = "Amazon API Gateway Console"

            if finding.aws_console_tabs:
                finding.notes.append(f"Located {len(finding.aws_console_tabs)} active AWS Management Console tab(s) in existing browser context.")
            else:
                finding.notes.append("CDP is active, but no AWS Console tabs were detected among open browser tabs.")

        except Exception as e:
            finding.notes.append(f"CDP tab enumeration warning: {e}")

        # 3. Optional Playwright async connection if installed
        try:
            self._inspect_with_playwright(finding)
        except Exception as e:
            finding.notes.append(f"Playwright CDP attachment note: {e}")

        return finding

    def _inspect_with_playwright(self, finding: BrowserConsoleFinding):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.cdp_url, timeout=2500)
                contexts = browser.contexts
                if contexts:
                    pages = contexts[0].pages
                    for page in pages:
                        title = page.title()
                        url = page.url
                        if "console.aws.amazon.com" in url:
                            finding.notes.append(f"Verified authenticated AWS page: '{title}' ({url[:60]}...)")
                browser.close()
        except Exception:
            pass
