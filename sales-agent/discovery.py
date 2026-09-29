"""Bounded public-web research and RSS/Atom prospect discovery. No third-party deps."""
import datetime
import codecs
import http.client
import ipaddress
import re
import socket
import ssl
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

MAX_BYTES = 1_000_000
MAX_TEXT = 16000
MAX_SOURCES = 20
TIMEOUT = 8


def decode_public_text(data, content_type=""):
    """Decode a bounded page using declared encodings before UTF-8 fallback."""
    head = data[:4096].decode("ascii", errors="ignore")
    candidates = []
    for pattern, source in (
        (r"charset\s*=\s*[\"']?([^;\s\"'>/]+)", content_type),
        (r"<meta\b[^>]*charset\s*=\s*[\"']?([^;\s\"'>/]+)", head),
        (r"<\?xml\b[^>]*encoding\s*=\s*[\"']([^\"']+)", head),
    ):
        match = re.search(pattern, source, re.I)
        if match:
            candidates.append(match.group(1))
    candidates.append("utf-8-sig")
    for encoding in candidates:
        try:
            normalized = codecs.lookup(encoding).name
            # Japanese sites commonly label Windows-31J bytes as Shift_JIS.
            if normalized == "shift_jis":
                normalized = "cp932"
            return data.decode(normalized)
        except (LookupError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _public_addresses(host, port):
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("Host has no addresses")
    for item in addresses:
        address = ipaddress.ip_address(item[4][0].split("%", 1)[0])
        if not address.is_global:
            raise ValueError("Only public internet addresses are allowed")
    return addresses


def _validate_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Use an http or https public URL")
    if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise ValueError("Credentials and nonstandard ports are not allowed")
    host = parsed.hostname.encode("idna").decode("ascii")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed, host, port


def fetch_public(url, redirects=3):
    """Resolve, validate, and connect to that exact IP, including on every redirect."""
    for step in range(redirects + 1):
        parsed, host, port = _validate_url(url)
        addresses = _public_addresses(host, port)
        family, socktype, proto, _, sockaddr = addresses[0]
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(TIMEOUT)
        conn = None
        try:
            sock.connect(sockaddr)
            if parsed.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
            conn = http.client.HTTPConnection(host, port, timeout=TIMEOUT)
            conn.sock = sock
            path = urllib.parse.urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
            conn.request("GET", path, headers={"User-Agent": "SalesResearch/1.0", "Accept": "text/html,application/rss+xml,application/atom+xml,text/xml", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or step == redirects:
                    raise ValueError("Redirect limit reached or missing destination")
                url = urllib.parse.urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError("Source returned HTTP %s" % response.status)
            mime = response.getheader("Content-Type", "text/html")
            if not any(kind in mime.lower() for kind in ("text/", "xml", "xhtml")):
                raise ValueError("Source must be text, HTML, RSS, or Atom")
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("Source exceeds 1 MB research limit")
            content = decode_public_text(data, mime)
            return {"url": url, "content": content, "content_type": mime}
        finally:
            if conn:
                conn.close()
            sock.close()


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.titles, self.ignored, self.in_title = [], [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.ignored += 1
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg"):
            self.ignored = max(0, self.ignored - 1)
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)
            if self.in_title:
                self.titles.append(data)


def extract_text(html):
    parser = _Text()
    parser.feed(html)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()[:MAX_TEXT], " ".join(parser.titles).strip()[:240]


def research_company(url):
    fetched = fetch_public(url)
    text, title = extract_text(fetched["content"])
    return {"url": fetched["url"], "title": title, "text": text, "kind": "public_page", "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "note": "公開情報。課題は事実と区別して仮説として扱う。"}


def _child_text(node, name):
    for child in node:
        if child.tag.rsplit("}", 1)[-1] == name:
            return " ".join(child.itertext()).strip()
    return ""


def parse_feed(content, source_url):
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", content, re.I):
        raise ValueError("Feed DTDs and entities are not supported")
    root = ET.fromstring(content)
    candidates = []
    for item in root.iter():
        if item.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
            continue
        title = _child_text(item, "title")
        description = _child_text(item, "description") or _child_text(item, "summary") or _child_text(item, "content")
        link = _child_text(item, "link")
        for child in item:
            if child.tag.rsplit("}", 1)[-1] == "link" and child.attrib.get("rel", "alternate") == "alternate":
                link = child.attrib.get("href") or link
                break
        link = urllib.parse.urljoin(source_url, link) if link else source_url
        _validate_url(link)
        clean, _ = extract_text(description)
        evidence = {"url": link, "title": title, "text": clean, "kind": "job_feed", "feed_url": source_url, "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        candidates.append({"company_name": "", "candidate_name": title or urllib.parse.urlsplit(link).hostname or "", "source_title": title, "identity_status": "unverified", "website": "", "source_url": link, "source_text": clean, "evidence": [evidence], "contact_email": "", "hypothesis": "求人・公開情報から企業名と業務課題を確認する必要があります。"})
        if len(candidates) >= MAX_SOURCES:
            break
    return candidates


def discover(feed_urls=None, company_urls=None):
    """Return evidence-backed drafts; never infer contact addresses or send mail."""
    feed_urls, company_urls = feed_urls or [], company_urls or []
    if len(feed_urls) + len(company_urls) > MAX_SOURCES:
        raise ValueError("At most 20 source URLs per discovery run")
    leads, seen = [], set()
    for url in feed_urls:
        fetched = fetch_public(url)
        for lead in parse_feed(fetched["content"], fetched["url"]):
            if lead["source_url"] not in seen:
                leads.append(lead)
                seen.add(lead["source_url"])
    for url in company_urls:
        evidence = research_company(url)
        if evidence["url"] in seen:
            continue
        seen.add(evidence["url"])
        leads.append({"company_name": "", "candidate_name": evidence["title"] or urllib.parse.urlsplit(evidence["url"]).hostname or "", "source_title": evidence["title"], "identity_status": "unverified", "website": evidence["url"], "source_url": evidence["url"], "source_text": evidence["text"], "evidence": [evidence], "contact_email": "", "hypothesis": "公開情報に基づいて業務課題を仮説化してください。"})
    return leads
