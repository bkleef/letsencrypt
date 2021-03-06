"""Tests for letsencrypt.client."""
import unittest

import configobj
import OpenSSL
import mock

from acme import jose

from letsencrypt import account
from letsencrypt import configuration
from letsencrypt import errors
from letsencrypt import le_util

from letsencrypt.tests import test_util


KEY = test_util.load_vector("rsa512_key.pem")
CSR_SAN = test_util.load_vector("csr-san.der")


class RegisterTest(unittest.TestCase):
    """Tests for letsencrypt.client.register."""

    def setUp(self):
        self.config = mock.MagicMock(rsa_key_size=1024)
        self.account_storage = account.AccountMemoryStorage()
        self.tos_cb = mock.MagicMock()

    def _call(self):
        from letsencrypt.client import register
        return register(self.config, self.account_storage, self.tos_cb)

    def test_no_tos(self):
        with mock.patch("letsencrypt.client.acme_client.Client") as mock_client:
            mock_client.register().terms_of_service = "http://tos"
            with mock.patch("letsencrypt.account.report_new_account"):
                self.tos_cb.return_value = False
                self.assertRaises(errors.Error, self._call)

                self.tos_cb.return_value = True
                self._call()

                self.tos_cb = None
                self._call()

    def test_it(self):
        with mock.patch("letsencrypt.client.acme_client.Client"):
            with mock.patch("letsencrypt.account."
                            "report_new_account"):
                self._call()


class ClientTest(unittest.TestCase):
    """Tests for letsencrypt.client.Client."""

    def setUp(self):
        self.config = mock.MagicMock(
            no_verify_ssl=False, config_dir="/etc/letsencrypt")
        # pylint: disable=star-args
        self.account = mock.MagicMock(**{"key.pem": KEY})

        from letsencrypt.client import Client
        with mock.patch("letsencrypt.client.acme_client.Client") as acme:
            self.acme_client = acme
            self.acme = acme.return_value = mock.MagicMock()
            self.client = Client(
                config=self.config, account_=self.account,
                dv_auth=None, installer=None)

    def test_init_acme_verify_ssl(self):
        self.acme_client.assert_called_once_with(
            new_reg_uri=mock.ANY, key=mock.ANY, verify_ssl=True)

    def _mock_obtain_certificate(self):
        self.client.auth_handler = mock.MagicMock()
        self.acme.request_issuance.return_value = mock.sentinel.certr
        self.acme.fetch_chain.return_value = mock.sentinel.chain

    def _check_obtain_certificate(self):
        self.client.auth_handler.get_authorizations.assert_called_once_with(
            ["example.com", "www.example.com"])
        self.acme.request_issuance.assert_called_once_with(
            jose.ComparableX509(OpenSSL.crypto.load_certificate_request(
                OpenSSL.crypto.FILETYPE_ASN1, CSR_SAN)),
            self.client.auth_handler.get_authorizations())
        self.acme.fetch_chain.assert_called_once_with(mock.sentinel.certr)

    def test_obtain_certificate_from_csr(self):
        self._mock_obtain_certificate()
        self.assertEqual(
            (mock.sentinel.certr, mock.sentinel.chain),
            self.client.obtain_certificate_from_csr(le_util.CSR(
                form="der", file=None, data=CSR_SAN)))
        self._check_obtain_certificate()

    @mock.patch("letsencrypt.client.crypto_util")
    def test_obtain_certificate(self, mock_crypto_util):
        self._mock_obtain_certificate()

        csr = le_util.CSR(form="der", file=None, data=CSR_SAN)
        mock_crypto_util.init_save_csr.return_value = csr
        mock_crypto_util.init_save_key.return_value = mock.sentinel.key
        domains = ["example.com", "www.example.com"]

        self.assertEqual(
            self.client.obtain_certificate(domains),
            (mock.sentinel.certr, mock.sentinel.chain, mock.sentinel.key, csr))

        mock_crypto_util.init_save_key.assert_called_once_with(
            self.config.rsa_key_size, self.config.key_dir)
        mock_crypto_util.init_save_csr.assert_called_once_with(
            mock.sentinel.key, domains, self.config.cert_dir)
        self._check_obtain_certificate()

    @mock.patch("letsencrypt.client.zope.component.getUtility")
    def test_report_renewal_status(self, mock_zope):
        # pylint: disable=protected-access
        cert = mock.MagicMock()
        cert.configuration = configobj.ConfigObj()
        cert.cli_config = configuration.RenewerConfiguration(self.config)

        cert.configuration["autorenew"] = "True"
        cert.configuration["autodeploy"] = "True"
        self.client._report_renewal_status(cert)
        msg = mock_zope().add_message.call_args[0][0]
        self.assertTrue("renewal and deployment has been" in msg)
        self.assertTrue(cert.cli_config.renewal_configs_dir in msg)

        cert.configuration["autorenew"] = "False"
        self.client._report_renewal_status(cert)
        msg = mock_zope().add_message.call_args[0][0]
        self.assertTrue("deployment but not automatic renewal" in msg)
        self.assertTrue(cert.cli_config.renewal_configs_dir in msg)

        cert.configuration["autodeploy"] = "False"
        self.client._report_renewal_status(cert)
        msg = mock_zope().add_message.call_args[0][0]
        self.assertTrue("renewal and deployment has not" in msg)
        self.assertTrue(cert.cli_config.renewal_configs_dir in msg)

        cert.configuration["autorenew"] = "True"
        self.client._report_renewal_status(cert)
        msg = mock_zope().add_message.call_args[0][0]
        self.assertTrue("renewal but not automatic deployment" in msg)
        self.assertTrue(cert.cli_config.renewal_configs_dir in msg)


class RollbackTest(unittest.TestCase):
    """Tests for letsencrypt.client.rollback."""

    def setUp(self):
        self.m_install = mock.MagicMock()

    @classmethod
    def _call(cls, checkpoints, side_effect):
        from letsencrypt.client import rollback
        with mock.patch("letsencrypt.client"
                        ".display_ops.pick_installer") as mock_pick_installer:
            mock_pick_installer.side_effect = side_effect
            rollback(None, checkpoints, {}, mock.MagicMock())

    def test_no_problems(self):
        self._call(1, self.m_install)
        self.assertEqual(self.m_install().rollback_checkpoints.call_count, 1)
        self.assertEqual(self.m_install().restart.call_count, 1)

    def test_no_installer(self):
        self._call(1, None) # Just make sure no exceptions are raised


if __name__ == "__main__":
    unittest.main()  # pragma: no cover
