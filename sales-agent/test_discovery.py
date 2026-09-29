import unittest
from unittest.mock import patch
import discovery


class PublicTextEncodingTests(unittest.TestCase):
    def test_shift_jis_meta_decodes_company_profile_without_http_charset(self):
        html='<html><head><meta charset="shift_jis"></head><body>株式会社 アイアンドユー 10名</body></html>'
        self.assertIn('アイアンドユー 10名', discovery.decode_public_text(html.encode('cp932'), 'text/html'))

    def test_http_charset_and_utf8_fallback(self):
        self.assertEqual(discovery.decode_public_text('従業員数25名'.encode('cp932'), 'text/plain; charset=Shift_JIS'), '従業員数25名')
        self.assertEqual(discovery.decode_public_text('従業員数25名'.encode(), 'text/plain'), '従業員数25名')


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
        self.assertEqual(result[0]["company_name"], "")
        self.assertEqual(result[0]["candidate_name"], "株式会社A 求人")
        self.assertEqual(result[0]["source_title"], "株式会社A 求人")
        self.assertEqual(result[0]["identity_status"], "unverified")
        self.assertEqual(result[0]["evidence"][0]["title"], "株式会社A 求人")
        atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title><link href="/jobs/1"/><summary>入力</summary></entry></feed>'
        candidate=discovery.parse_feed(atom, "https://example.com/feed")[0]
        self.assertEqual(candidate["source_url"], "https://example.com/jobs/1")
        self.assertEqual(candidate["company_name"], "")

    def test_job_title_even_with_company_word_is_not_verified_identity(self):
        rss='<rss><channel><item><title>株式会社対象企業 採用情報</title><link>https://jobs.example.com/1</link><description>採用中</description></item></channel></rss>'
        candidate=discovery.parse_feed(rss,'https://jobs.example.com/feed')[0]
        self.assertEqual(candidate['company_name'],'')
        self.assertEqual(candidate['candidate_name'],'株式会社対象企業 採用情報')
        self.assertEqual(candidate['identity_status'],'unverified')

    def test_entity_feed_rejected(self):
        with self.assertRaises(ValueError):
            discovery.parse_feed('<!DOCTYPE rss [<!ENTITY a "x">]><rss/>', "https://example.com")

    def test_discovery_deduplicates_and_keeps_evidence(self):
        data = {"url": "https://example.com", "content": "<title>A社</title><p>データ入力</p>", "content_type": "text/html"}
        with patch.object(discovery, "fetch_public", return_value=data):
            leads = discovery.discover(company_urls=["https://example.com", "https://example.com"])
        self.assertEqual(len(leads), 1)
        self.assertEqual(leads[0]["evidence"][0]["text"], "A社 データ入力")
        self.assertEqual(leads[0]["company_name"], "")
        self.assertEqual(leads[0]["candidate_name"], "A社")
        self.assertEqual(leads[0]["identity_status"], "unverified")

    def test_company_homepage_title_is_not_a_legal_entity_verification(self):
        data={"url":"https://example.com/about","content":"<title>株式会社対象企業 | 会社概要</title><p>Excel集計</p>","content_type":"text/html"}
        with patch.object(discovery,"fetch_public",return_value=data):
            candidate=discovery.discover(company_urls=["https://example.com/about"])[0]
        self.assertEqual(candidate["company_name"],"")
        self.assertEqual(candidate["candidate_name"],"株式会社対象企業 | 会社概要")
        self.assertEqual(candidate["source_title"],"株式会社対象企業 | 会社概要")
        self.assertEqual(candidate["identity_status"],"unverified")
        self.assertEqual(candidate["source_url"],"https://example.com/about")

    def test_titleless_source_uses_hostname_only_as_display_candidate(self):
        data={"url":"https://example.com/about","content":"<p>Excel集計</p>","content_type":"text/html"}
        with patch.object(discovery,"fetch_public",return_value=data):
            candidate=discovery.discover(company_urls=["https://example.com/about"])[0]
        self.assertEqual(candidate["candidate_name"],"example.com")
        self.assertEqual(candidate["source_title"],"")
        self.assertEqual(candidate["company_name"],"")


if __name__ == "__main__":
    unittest.main()
