"""Config flow for Bitaxe/NerdAxe integration."""

import logging
from typing import Any, Optional
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac

from .api_client import BitaxeAPIClient
from .const import (
    CONF_DEVICE_NAME,
    CONF_DEVICE_SLUG,
    CONF_ENTRY_TYPE,
    CONF_HOST,
    CONF_MINER_TYPE,
    CONF_POOLS,
    CONNECTION_TIMEOUT,
    DOMAIN,
    ENTRY_TYPE_FLEET,
    ENTRY_TYPE_MINER,
    ERROR_CANNOT_CONNECT,
    ERROR_CONNECTION_TIMEOUT,
    ERROR_INVALID_HOST,
    ERROR_UNKNOWN,
    MINER_TYPE_BITAXE,
    MINER_TYPE_NERDAXE,
)
from .utils import normalize_identifier

_LOGGER = logging.getLogger(__name__)


class AxeosConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Bitaxe/NerdAxe."""

    VERSION = 1
    MINOR_VERSION = 1

    _pending_data: dict[str, Any] = {}
    _pending_info: dict[str, Any] = {}

    def _fleet_entry_exists(self) -> bool:
        """Return True when a standalone fleet entry already exists."""
        return any(
            entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MINER) == ENTRY_TYPE_FLEET
            for entry in self._async_current_entries()
        )

    @staticmethod
    def _normalize_host(raw_host: str) -> str:
        """Normalize user input to a plain host/IP without scheme/path."""
        candidate = raw_host.strip()
        if "://" in candidate:
            parsed = urlparse(candidate)
            return (parsed.hostname or "").strip()

        return candidate.split("/", 1)[0].strip()

    @staticmethod
    def _mac_from_info(info: dict[str, Any]) -> str | None:
        """Extract and normalize a stable unique ID from API data."""
        mac = info.get("macAddr")
        if not isinstance(mac, str) or not mac.strip():
            return None

        try:
            return format_mac(mac)
        except ValueError:
            _LOGGER.debug("Device returned invalid macAddr: %s", mac)
            return None

    @staticmethod
    def _discovered_device_name(
        info: dict[str, Any], host: str, miner_type: str
    ) -> str:
        """Build display name using discovered hostname when available."""
        hostname = info.get("hostname")
        if isinstance(hostname, str) and hostname.strip():
            return f"{miner_type.capitalize()} {hostname.strip()}"
        return f"{miner_type.capitalize()} {host}"

    @staticmethod
    def _discovered_device_slug(info: dict[str, Any], host: str) -> str:
        """Build normalized slug using discovered hostname when available."""
        hostname = info.get("hostname")
        if isinstance(hostname, str) and hostname.strip():
            return normalize_identifier(hostname)
        return normalize_identifier(host)

    async def _async_validate_and_fetch_info(
        self, host: str
    ) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        """Validate host connectivity and return (error, system_info)."""
        if not host or not isinstance(host, str) or host.startswith("http"):
            return ERROR_INVALID_HOST, None

        try:
            session = async_get_clientsession(self.hass)
            client = BitaxeAPIClient(host, session)
            info = await client.get_system_info(timeout=CONNECTION_TIMEOUT)
            if not isinstance(info, dict):
                return ERROR_UNKNOWN, None
            return None, info
        except TimeoutError:
            _LOGGER.warning("Timeout connecting to %s", host)
            return ERROR_CONNECTION_TIMEOUT, None
        except ConnectionError:
            _LOGGER.warning("Cannot connect to %s", host)
            return ERROR_CANNOT_CONNECT, None
        except Exception as err:  # broad-except: map unexpected validation errors
            _LOGGER.exception("Error validating host %s: %s", host, err)
            return ERROR_UNKNOWN, None

    def _find_existing_pools(self) -> list[dict[str, Any]]:
        """Return pool profiles from the first already-configured entry that has them."""
        for entry in self._async_current_entries():
            pools = entry.data.get(CONF_POOLS)
            if pools:
                return pools
        return []

    def _miner_hostname(self) -> str:
        """Return the hostname suffix to use for pool users."""
        return str(
            self._pending_info.get("hostname")
            or self._pending_data.get(CONF_DEVICE_SLUG, "")
        ).strip()

    def _user_with_hostname_suffix(self, base_user: str) -> str:
        """Ensure a pool username ends with .hostname for the miner being added."""
        user = str(base_user or "").strip()
        hostname = self._miner_hostname()
        if not user or not hostname:
            return user

        # If the user already ends with another configured miner suffix,
        # replace that suffix with the current miner hostname.
        for entry in self._async_current_entries():
            existing_slug = str(entry.data.get(CONF_DEVICE_SLUG, "")).strip()
            if existing_slug and user.endswith(f".{existing_slug}"):
                user = user[: -(len(existing_slug) + 1)]
                break

        if user.endswith(f".{hostname}"):
            return user

        return f"{user}.{hostname}"

    def _user_without_hostname_suffix(self, value: str) -> str:
        """Return username input value without any known .hostname suffix."""
        user = str(value or "").strip()
        if not user:
            return user

        current_hostname = self._miner_hostname()
        if current_hostname and user.endswith(f".{current_hostname}"):
            return user[: -(len(current_hostname) + 1)]

        for entry in self._async_current_entries():
            existing_slug = str(entry.data.get(CONF_DEVICE_SLUG, "")).strip()
            if existing_slug and user.endswith(f".{existing_slug}"):
                return user[: -(len(existing_slug) + 1)]

        return user

    def _pool_schema(self) -> vol.Schema:
        """Build schema for up to three optional pool profiles.

        When other miners are already configured, copies their pool profiles and
        appends .hostname to each username so the new miner is identified.
        """
        existing_pools = self._find_existing_pools()

        if existing_pools:
            p1 = existing_pools[0] if len(existing_pools) > 0 else {}
            p2 = existing_pools[1] if len(existing_pools) > 1 else {}
            p3 = existing_pools[2] if len(existing_pools) > 2 else {}
            defaults = {
                "pool1_name": p1.get("name", "Primary Pool"),
                "pool1_url": p1.get("stratum_url", ""),
                "pool1_port": p1.get("stratum_port", 3333),
                "pool1_user": self._user_without_hostname_suffix(
                    p1.get("stratum_user", "")
                ),
                "pool1_password": p1.get("stratum_password", ""),
                "pool2_name": p2.get("name", ""),
                "pool2_url": p2.get("stratum_url", ""),
                "pool2_port": p2.get("stratum_port", 3333),
                "pool2_user": self._user_without_hostname_suffix(
                    p2.get("stratum_user", "")
                ),
                "pool2_password": p2.get("stratum_password", ""),
                "pool3_name": p3.get("name", ""),
                "pool3_url": p3.get("stratum_url", ""),
                "pool3_port": p3.get("stratum_port", 3333),
                "pool3_user": self._user_without_hostname_suffix(
                    p3.get("stratum_user", "")
                ),
                "pool3_password": p3.get("stratum_password", ""),
            }
        else:
            defaults = {
                "pool1_name": "Primary Pool",
                "pool1_url": self._pending_info.get("stratumURL", ""),
                "pool1_port": self._pending_info.get("stratumPort", 3333),
                "pool1_user": self._user_without_hostname_suffix(
                    self._pending_info.get("stratumUser", "")
                ),
                "pool1_password": "",
                "pool2_name": "",
                "pool2_url": "",
                "pool2_port": 3333,
                "pool2_user": "",
                "pool2_password": "",
                "pool3_name": "",
                "pool3_url": "",
                "pool3_port": 3333,
                "pool3_user": "",
                "pool3_password": "",
            }

        return vol.Schema(
            {
                vol.Optional("pool1_name", default=defaults["pool1_name"]): str,
                vol.Optional("pool1_url", default=defaults["pool1_url"]): str,
                vol.Optional("pool1_port", default=defaults["pool1_port"]): int,
                vol.Optional("pool1_user", default=defaults["pool1_user"]): str,
                vol.Optional("pool1_password", default=defaults["pool1_password"]): str,
                vol.Optional("pool2_name", default=defaults["pool2_name"]): str,
                vol.Optional("pool2_url", default=defaults["pool2_url"]): str,
                vol.Optional("pool2_port", default=defaults["pool2_port"]): int,
                vol.Optional("pool2_user", default=defaults["pool2_user"]): str,
                vol.Optional("pool2_password", default=defaults["pool2_password"]): str,
                vol.Optional("pool3_name", default=defaults["pool3_name"]): str,
                vol.Optional("pool3_url", default=defaults["pool3_url"]): str,
                vol.Optional("pool3_port", default=defaults["pool3_port"]): int,
                vol.Optional("pool3_user", default=defaults["pool3_user"]): str,
                vol.Optional("pool3_password", default=defaults["pool3_password"]): str,
            }
        )

    def _extract_pools(
        self, user_input: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], bool]:
        """Extract complete pools and detect partial definitions."""
        pools: list[dict[str, Any]] = []
        has_partial = False

        for idx in (1, 2, 3):
            name = str(user_input.get(f"pool{idx}_name", "")).strip()
            url = str(user_input.get(f"pool{idx}_url", "")).strip()
            port = user_input.get(f"pool{idx}_port")
            user = str(user_input.get(f"pool{idx}_user", "")).strip()
            password = str(user_input.get(f"pool{idx}_password", "")).strip()

            if not any([name, url, port, user, password]):
                continue

            if not all([url, user, password]) or not isinstance(port, int):
                has_partial = True
                continue

            if port < 1 or port > 65535:
                has_partial = True
                continue

            pools.append(
                {
                    "name": name or f"Pool {idx}",
                    "stratum_url": url,
                    "stratum_port": int(port),
                    "stratum_user": self._user_with_hostname_suffix(user),
                    "stratum_password": password,
                }
            )

        return pools, has_partial

    async def async_step_user(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle setup type selection."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["miner", "fleet"],
        )

    async def async_step_fleet(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Create a standalone fleet entry."""
        if self._fleet_entry_exists():
            return self.async_abort(reason="fleet_already_configured")

        await self.async_set_unique_id(f"{DOMAIN}_fleet")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title="AxeOS Fleet",
            data={
                CONF_ENTRY_TYPE: ENTRY_TYPE_FLEET,
                CONF_DEVICE_NAME: "AxeOS Fleet",
                CONF_DEVICE_SLUG: "fleet",
            },
        )

    async def async_step_miner(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle miner setup - select miner type and host/IP."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self.miner_type = user_input[CONF_MINER_TYPE]
            host = self._normalize_host(user_input.get(CONF_HOST, ""))
            error, info = await self._async_validate_and_fetch_info(host)
            if error:
                errors["base"] = error
            else:
                assert info is not None
                device_name = self._discovered_device_name(info, host, self.miner_type)
                device_slug = self._discovered_device_slug(info, host)
                unique_id = self._mac_from_info(info)

                if unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured(
                        updates={
                            CONF_HOST: host,
                            CONF_MINER_TYPE: self.miner_type,
                            CONF_DEVICE_NAME: device_name,
                            CONF_DEVICE_SLUG: device_slug,
                        }
                    )
                else:
                    for entry in self._async_current_entries():
                        if entry.data.get(CONF_HOST) == host:
                            return self.async_abort(reason="already_configured")

                self._pending_info = info
                self._pending_data = {
                    CONF_ENTRY_TYPE: ENTRY_TYPE_MINER,
                    CONF_HOST: host,
                    CONF_MINER_TYPE: self.miner_type,
                    CONF_DEVICE_NAME: device_name,
                    CONF_DEVICE_SLUG: device_slug,
                }
                return await self.async_step_pools()

        return self.async_show_form(
            step_id="miner",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MINER_TYPE, default=MINER_TYPE_BITAXE): vol.In(
                        {
                            MINER_TYPE_BITAXE: "Bitaxe",
                            MINER_TYPE_NERDAXE: "NerdAxe",
                        }
                    ),
                    vol.Required(CONF_HOST): str,
                }
            ),
            errors=errors,
        )

    async def async_step_host(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle host/IP input step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = self._normalize_host(user_input.get(CONF_HOST, ""))
            error, info = await self._async_validate_and_fetch_info(host)
            if error:
                errors["base"] = error
            else:
                assert info is not None
                device_name = self._discovered_device_name(info, host, self.miner_type)
                device_slug = self._discovered_device_slug(info, host)
                unique_id = self._mac_from_info(info)

                if unique_id:
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured(
                        updates={
                            CONF_HOST: host,
                            CONF_MINER_TYPE: self.miner_type,
                            CONF_DEVICE_NAME: device_name,
                            CONF_DEVICE_SLUG: device_slug,
                        }
                    )
                else:
                    for entry in self._async_current_entries():
                        if entry.data.get(CONF_HOST) == host:
                            return self.async_abort(reason="already_configured")

                self._pending_info = info
                self._pending_data = {
                    CONF_HOST: host,
                    CONF_MINER_TYPE: self.miner_type,
                    CONF_DEVICE_NAME: device_name,
                    CONF_DEVICE_SLUG: device_slug,
                }
                return await self.async_step_pools()

        return self.async_show_form(
            step_id="host",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
            description_placeholders={"miner_type": self.miner_type.capitalize()},
        )

    async def async_step_pools(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Optional pool profiles (up to 3)."""
        if user_input is not None:
            pools, has_partial = self._extract_pools(user_input)
            if has_partial:
                return self.async_show_form(
                    step_id="pools",
                    data_schema=self._pool_schema(),
                    errors={"base": "invalid_pool"},
                    description_placeholders={
                        "device_name": self._pending_data.get(CONF_DEVICE_NAME, "Miner"),
                        "miner_hostname": str(self._pending_info.get("hostname") or self._pending_data.get(CONF_DEVICE_SLUG, "")).strip(),
                    },
                )

            return self.async_create_entry(
                title=self._pending_data[CONF_DEVICE_NAME],
                data={
                    **self._pending_data,
                    CONF_POOLS: pools,
                },
            )

        return self.async_show_form(
            step_id="pools",
            data_schema=self._pool_schema(),
            description_placeholders={
                "device_name": self._pending_data.get(CONF_DEVICE_NAME, "Miner"),
                "miner_hostname": str(self._pending_info.get("hostname") or self._pending_data.get(CONF_DEVICE_SLUG, "")).strip(),
            },
        )

    async def async_step_reconfigure(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> FlowResult:
        """Handle config entry reconfiguration from the UI."""
        reconfigure_entry = self._get_reconfigure_entry()
        if (
            reconfigure_entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_MINER)
            == ENTRY_TYPE_FLEET
        ):
            return self.async_abort(reason="reconfigure_not_supported")

        current_type = reconfigure_entry.data.get(CONF_MINER_TYPE, MINER_TYPE_BITAXE)
        current_host = reconfigure_entry.data.get(CONF_HOST, "")

        if user_input is not None:
            miner_type = user_input[CONF_MINER_TYPE]
            host = self._normalize_host(user_input[CONF_HOST])
            error, info = await self._async_validate_and_fetch_info(host)
            if error:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_MINER_TYPE, default=miner_type): vol.In(
                                {
                                    MINER_TYPE_BITAXE: "Bitaxe",
                                    MINER_TYPE_NERDAXE: "NerdAxe",
                                }
                            ),
                            vol.Required(CONF_HOST, default=host): str,
                        }
                    ),
                    errors={"base": error},
                    description_placeholders={"miner_type": miner_type.capitalize()},
                )

            assert info is not None
            unique_id = self._mac_from_info(info)
            if unique_id:
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_mismatch()

            return self.async_update_reload_and_abort(
                reconfigure_entry,
                data_updates={
                    CONF_HOST: host,
                    CONF_MINER_TYPE: miner_type,
                    CONF_DEVICE_NAME: self._discovered_device_name(
                        info, host, miner_type
                    ),
                    CONF_DEVICE_SLUG: self._discovered_device_slug(info, host),
                    CONF_POOLS: reconfigure_entry.data.get(CONF_POOLS, []),
                },
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MINER_TYPE, default=current_type): vol.In(
                        {
                            MINER_TYPE_BITAXE: "Bitaxe",
                            MINER_TYPE_NERDAXE: "NerdAxe",
                        }
                    ),
                    vol.Required(CONF_HOST, default=current_host): str,
                }
            ),
            description_placeholders={"miner_type": current_type.capitalize()},
        )
