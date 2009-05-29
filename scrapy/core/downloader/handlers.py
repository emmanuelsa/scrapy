"""
Download handlers for different schemes
"""
from __future__ import with_statement

import urlparse

from twisted.internet import reactor
from twisted.web import error as web_error

try:
    from twisted.internet import ssl
except ImportError:
    pass

from scrapy import optional_features
from scrapy.core import signals
from scrapy.http import Headers
from scrapy.core.exceptions import NotSupported
from scrapy.utils.defer import defer_succeed
from scrapy.conf import settings

from scrapy.core.downloader.dnscache import DNSCache
from scrapy.core.downloader.responsetypes import responsetypes
from scrapy.core.downloader.webclient import ScrapyHTTPClientFactory as HTTPClientFactory

default_timeout = settings.getint('DOWNLOAD_TIMEOUT')
ssl_supported = 'ssl' in optional_features

# Cache for dns lookups.
dnscache = DNSCache()

def download_any(request, spider):
    scheme = request.url.scheme
    if scheme == 'http':
        return download_http(request, spider)
    elif scheme == 'https':
        if ssl_supported:
            return download_https(request, spider)
        else:
            raise NotSupported("HTTPS not supported: install pyopenssl library")
    elif request.url.scheme == 'file':
        return download_file(request, spider)
    else:
        raise NotSupported("Unsupported URL scheme '%s' in: <%s>" % (request.url.scheme, request.url))

def create_factory(request, spider):
    """Return HTTPClientFactory for the given Request"""
    url = urlparse.urldefrag(request.url)[0]
    timeout = getattr(spider, "download_timeout", None) or default_timeout

    factory = HTTPClientFactory(url=url, # never pass unicode urls to twisted
                                method=request.method,
                                body=request.body or None, # see http://dev.scrapy.org/ticket/60
                                headers=request.headers,
                                timeout=timeout)

    def _create_response(body):
        body = body or ''
        status = int(factory.status)
        headers = Headers(factory.response_headers)
        respcls = responsetypes.from_args(headers=headers, url=url)
        r = respcls(url=request.url, status=status, headers=headers, body=body)
        signals.send_catch_log(signal=signals.request_uploaded, sender='download_http', request=request, spider=spider)
        signals.send_catch_log(signal=signals.response_downloaded, sender='download_http', response=r, spider=spider)
        return r

    factory.deferred.addCallbacks(_create_response)
    return factory

def download_http(request, spider):
    """Return a deferred for the HTTP download"""
    factory = create_factory(request, spider)
    ip = dnscache.get(request.url.hostname)
    port = request.url.port
    reactor.connectTCP(ip, port or 80, factory)
    return factory.deferred

def download_https(request, spider):
    """Return a deferred for the HTTPS download"""
    factory = create_factory(request, spider)
    ip = dnscache.get(request.url.hostname)
    port = request.url.port
    contextFactory = ssl.ClientContextFactory()
    reactor.connectSSL(ip, port or 443, factory, contextFactory)
    return factory.deferred

def download_file(request, spider) :
    """Return a deferred for a file download."""
    filepath = request.url.split("file://")[1]
    with open(filepath) as f:
        body = f.read()
        respcls = responsetypes.from_args(filename=filepath, body=body)
        response = respcls(url=request.url, body=body)

    return defer_succeed(response)