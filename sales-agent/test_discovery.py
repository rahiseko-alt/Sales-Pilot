import unittest
from unittest.mock import patch
import discovery


class DiscoveryTests(unittest.TestCase):
    def test_private_and_mixed_dns_rejected(self):
        for ips in (["127.0.0.1"], ["169.254.169.254"], ["8.8.8.8", "10.0.0.1"], ["::1"]):
            values = [(2, 1, 6, "", (ip, 443)) for ip in ips]
            with patch.object(discovery.socket, "getaddrinfo", return_value=values):
                with self.assertRaises(ValueError):
                    discovery._public_addresses("example.test", 443)

    def test_url_limits(self):
        for url in ("file:///etc/passwd", "http://user:secret@example.com", "http://example.com:8080"):
            with self.assertRaises(ValueError):
                discovery._validate_url(url)

    def test_html_discards_script(self):
        text, title = discovery.extract_text("<title>会社</title><script>secret()</script><p>Excel 入力</p>")
        self.assertEqual(title, "会社")
        self.assertIn("Excel 入力", text)
        self.assertNotIn("secret", text)

    def test_rss_and_atom(self):
        rss = '<rss><channel><item><title>株式会社A 求人</title><link>https://example.com/job</link><description>&lt;p&gt;Excel入力&lt;/p&gt;</description></item></channel></rss>'
        result = discovery.parse_feed(rss, "https://example.com/feed")
        self.assertEqual(result[0]["source_text"], "Excel入力")
        self.assertEqual(result[0]["contact_email"], "")
        atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title><link href="/jobs/1"/><summary>入力</summary></entry></feed>'
        self.assertEqual(discovery.parse_feed(atom, "https://example.com/feed")[0]["source_url"], "https://example.com/jobs/1")

    def test_entity_feed_rejected(self):
        with self.assertRaises(ValueError):
            discovery.parse_feed('<!DOCTYPE rss [<!ENTITY a "x">]><rss/>', "https://example.com")

    def test_discovery_deduplicates_and_keeps_evidence(self):
        data = {"url": "https://example.com", "content": "<title>A社</title><p>データ入力</p>", "content_type": "text/html"}
        with patch.object(discovery, "fetch_public", return_value=data):
            leads = discovery.discover(company_urls=["https://example.com", "https://example.com"])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["evidence"][0]["text"], "A社 データ入力")


if __name__ == "__main__":
    unittest.main()
