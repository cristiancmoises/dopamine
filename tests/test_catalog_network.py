import os,socket,ssl,unittest
from unittest.mock import patch,MagicMock
from app import real_photos as p

class CatalogTransportTests(unittest.TestCase):
    def test_ipv4_is_opt_in(self):
        with patch.dict(os.environ,{'DOPAMINE_CATALOG_IPV4':'0'}):
            self.assertFalse(any(isinstance(h,p.CatalogIPv4Handler) for h in p.catalog_opener().handlers))
        with patch.dict(os.environ,{'DOPAMINE_CATALOG_IPV4':'1'}):
            handler=next(h for h in p.catalog_opener().handlers if isinstance(h,p.CatalogIPv4Handler))
            self.assertTrue(handler._context.check_hostname)
            self.assertEqual(handler._context.verify_mode,ssl.CERT_REQUIRED)
    def test_ipv4_resolution_and_timeout(self):
        connection=MagicMock()
        with patch.object(p.socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.0.2.1',443))]) as dns,patch.object(p.socket,'socket',return_value=connection):
            self.assertIs(p.ipv4_connection(('en.wikipedia.org',443),7),connection)
            dns.assert_called_once_with('en.wikipedia.org',443,socket.AF_INET,socket.SOCK_STREAM)
            connection.settimeout.assert_called_once_with(7)
            connection.connect.assert_called_once_with(('192.0.2.1',443))
    def test_failed_socket_closed(self):
        connection=MagicMock();connection.connect.side_effect=TimeoutError('test')
        with patch.object(p.socket,'getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('192.0.2.1',443))]),patch.object(p.socket,'socket',return_value=connection):
            with self.assertRaises(TimeoutError):p.ipv4_connection(('en.wikipedia.org',443))
            connection.close.assert_called_once()
    def test_transport_does_not_relax_source_allowlist(self):
        with patch.dict(os.environ,{'DOPAMINE_CATALOG_IPV4':'1'}):
            for url in ['http://en.wikipedia.org/w/api.php','https://127.0.0.1/w/api.php','https://evil.example/a.jpg']:
                with self.assertRaises(p.CatalogError):p.fetch(url,api=True)
