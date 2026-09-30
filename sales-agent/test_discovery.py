import unittest
import json
import http.client
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
            result = discovery.discover(company_urls=["https://example.com", "https://example.com"])
        leads=result['leads']
        self.assertEqual(len(leads), 1)
        self.assertEqual(result['errors'],[])
        self.assertEqual(leads[0]["evidence"][0]["text"], "A社 データ入力")
        self.assertEqual(leads[0]["company_name"], "")
        self.assertEqual(leads[0]["candidate_name"], "A社")
        self.assertEqual(leads[0]["identity_status"], "unverified")

    def test_company_homepage_title_is_not_a_legal_entity_verification(self):
        data={"url":"https://example.com/about","content":"<title>株式会社対象企業 | 会社概要</title><p>Excel集計</p>","content_type":"text/html"}
        with patch.object(discovery,"fetch_public",return_value=data):
            candidate=discovery.discover(company_urls=["https://example.com/about"])['leads'][0]
        self.assertEqual(candidate["company_name"],"")
        self.assertEqual(candidate["candidate_name"],"株式会社対象企業 | 会社概要")
        self.assertEqual(candidate["source_title"],"株式会社対象企業 | 会社概要")
        self.assertEqual(candidate["identity_status"],"unverified")
        self.assertEqual(candidate["source_url"],"https://example.com/about")

    def test_titleless_source_uses_hostname_only_as_display_candidate(self):
        data={"url":"https://example.com/about","content":"<p>Excel集計</p>","content_type":"text/html"}
        with patch.object(discovery,"fetch_public",return_value=data):
            candidate=discovery.discover(company_urls=["https://example.com/about"])['leads'][0]
        self.assertEqual(candidate["candidate_name"],"example.com")
        self.assertEqual(candidate["source_title"],"")
        self.assertEqual(candidate["company_name"],"")

    def test_feed_fetch_failure_isolated_from_later_valid_feed(self):
        first='https://bad.example.com/jobs?token=TOKEN_SENTINEL_SECRET'
        second='https://good.example.com/jobs'
        valid='<rss><channel><item><title>物流事務</title><link>https://good.example.com/1</link></item></channel></rss>'
        def fetch(url):
            if url==first:raise http.client.BadStatusLine('HTTP_SENTINEL_SECRET')
            return {'url':url,'content':valid,'content_type':'application/rss+xml'}
        with patch.object(discovery,'fetch_public',side_effect=fetch):result=discovery.discover(feed_urls=[first,second])
        self.assertEqual(len(result['leads']),1)
        self.assertEqual(result['leads'][0]['source_url'],'https://good.example.com/1')
        self.assertEqual(result['errors'],[{'kind':'feed','host':'bad.example.com','index':1,'reason':'fetch_failed'}])
        self.assertNotIn('SENTINEL_SECRET',json.dumps(result))

    def test_feed_parse_failure_isolated_from_later_valid_company_page(self):
        broken='https://bad.example.com/feed'
        good='https://good.example.com/about'
        def fetch(url):
            if url==broken:return {'url':url,'content':'<!DOCTYPE rss><rss/>','content_type':'application/rss+xml'}
            return {'url':url,'content':'<title>採用情報</title><p>Excel入力</p>','content_type':'text/html'}
        with patch.object(discovery,'fetch_public',side_effect=fetch):result=discovery.discover(feed_urls=[broken],company_urls=[good])
        self.assertEqual(len(result['leads']),1)
        self.assertEqual(result['leads'][0]['source_url'],good)
        self.assertEqual(result['errors'],[{'kind':'feed','host':'bad.example.com','index':1,'reason':'parse_failed'}])

    def test_company_fetch_and_parse_failures_do_not_stop_later_company(self):
        urls=['https://first.example.com/about','https://second.example.com/about','https://good.example.com/about']
        def fetch(url):
            if url==urls[0]:raise TimeoutError('TOKEN_SENTINEL_SECRET')
            return {'url':url,'content':('PARSE_SENTINEL_SECRET' if url==urls[1] else '<title>採用</title><p>入力</p>'),'content_type':'text/html'}
        original=discovery.extract_text
        def parse(content):
            if content=='PARSE_SENTINEL_SECRET':raise ValueError('EXCEPTION_SENTINEL_SECRET')
            return original(content)
        with patch.object(discovery,'fetch_public',side_effect=fetch),patch.object(discovery,'extract_text',side_effect=parse):
            result=discovery.discover(company_urls=urls)
        self.assertEqual([lead['source_url'] for lead in result['leads']],[urls[2]])
        self.assertEqual([error['reason'] for error in result['errors']],['fetch_failed','parse_failed'])
        self.assertEqual([error['index'] for error in result['errors']],[1,2])
        self.assertNotIn('SENTINEL_SECRET',json.dumps(result))

    def test_all_sources_failing_are_reported_without_abort(self):
        urls=['https://first.example.com/feed','https://second.example.com/company']
        with patch.object(discovery,'fetch_public',side_effect=TimeoutError('SECRET_SENTINEL')):
            result=discovery.discover(feed_urls=urls[:1],company_urls=urls[1:])
        self.assertEqual(result['leads'],[])
        self.assertEqual(len(result['errors']),2)
        self.assertEqual([e['kind'] for e in result['errors']],['feed','company'])

    def test_duplicate_successful_source_is_fetched_once(self):
        url='https://example.com/about'
        data={'url':url,'content':'<title>企業情報</title><p>Excel</p>','content_type':'text/html'}
        with patch.object(discovery,'fetch_public',return_value=data) as fetch:
            result=discovery.discover(company_urls=[url,url])
        self.assertEqual(len(result['leads']),1)
        self.assertEqual(result['errors'],[])
        fetch.assert_called_once_with(url)


if __name__ == "__main__":
    unittest.main()
