from __future__ import annotations

import abc
import asyncio
import json
import logging
import time
import warnings
from datetime import date
from typing import *

import fastapi
import langcodes
import pytz
import starlette.datastructures
from uniserde import JsonDoc

import rio
import rio.assets

from .. import (
    assets,
    data_models,
    language_info,
    routing,
    session,
    user_settings_module,
    utils,
)

__all__ = ["AbstractAppServer"]


class AbstractAppServer(abc.ABC):
    def __init__(
        self,
        app: rio.App,
        *,
        running_in_window: bool,
        debug_mode: bool,
    ):
        self.app = app
        self.running_in_window = running_in_window
        self.debug_mode = debug_mode

        self._permanently_hosted_assets = set[assets.HostedAsset]()
        self._session_receive_tasks = dict[rio.Session, asyncio.Task[object]]()

    @abc.abstractmethod
    async def file_chooser(
        self,
        session: rio.Session,
        *,
        file_extensions: Iterable[str] | None = None,
        multiple: bool = False,
    ) -> utils.FileInfo | tuple[utils.FileInfo, ...]:
        raise NotImplementedError

    @abc.abstractmethod
    def weakly_host_asset(self, asset: assets.HostedAsset) -> str:
        """
        Hosts an asset as long as it is alive. Returns the asset's URL as a
        string.
        """
        raise NotImplementedError

    def host_asset_permanently(self, asset: assets.HostedAsset) -> str:
        self._permanently_hosted_assets.add(asset)
        return self.weakly_host_asset(asset)

    def host_asset_with_timeout(
        self, asset: assets.HostedAsset, timeout: float
    ) -> str:
        """
        Hosts an asset for a limited time. Returns the asset's URL as a string.
        """
        # FIXME: This should generate a new url that expires after the given
        # timeout
        url = self.weakly_host_asset(asset)

        async def keep_alive():
            await asyncio.sleep(timeout)
            _ = asset

        asyncio.create_task(
            keep_alive(), name=f"Keep asset {asset} alive for {timeout} sec"
        )

        return url

    def _after_session_closed(self, session: rio.Session) -> None:
        """
        Called by `Session.close()`. Gives the server an opportunity to clean
        up.
        """
        # Stop the task that's listening for incoming messages
        task = self._session_receive_tasks.pop(session)
        task.cancel()

    async def create_session(
        self,
        initial_message: data_models.InitialClientMessage | None,
        *,
        websocket: fastapi.WebSocket | None,
        send_message: Callable[[JsonDoc], Awaitable[None]],
        receive_message: Callable[[], Awaitable[JsonDoc]],
        url: rio.URL,
        client_ip: str,
        client_port: int,
        http_headers: starlette.datastructures.Headers,
    ) -> rio.Session:
        """
        Creates a new session.

        ## Raises

        `NavigationFailed`: If a page guard crashes
        """
        if initial_message is None:
            initial_message = data_models.InitialClientMessage.from_defaults()

        # Normalize and deduplicate the languages
        preferred_languages: list[str] = []

        for language in initial_message.preferred_languages:
            try:
                language = langcodes.standardize_tag(language)
            except ValueError:
                continue

            if language not in preferred_languages:
                preferred_languages.append(language)

        if len(preferred_languages) == 0:
            preferred_languages.append("en-US")

        # Get locale information
        if len(initial_message.decimal_separator) != 1:
            logging.warning(
                f'Client sent invalid decimal separator "{initial_message.decimal_separator}". Using "." instead.'
            )
            initial_message.decimal_separator = "."

        if len(initial_message.thousands_separator) > 1:
            logging.warning(
                f'Client sent invalid thousands separator "{initial_message.thousands_separator}". Using "" instead.'
            )
            initial_message.thousands_separator = ""

        # There does not seem to be any good way to determine the first day of
        # the week in JavaScript. Look up the first day of the week based on
        # the preferred language.
        first_day_of_week = language_info.get_week_start_day(
            preferred_languages[0]
        )

        # Make sure the date format string is valid
        try:
            formatted_date = date(3333, 11, 22).strftime(
                initial_message.date_format_string
            )
        except ValueError:
            date_format_string_is_valid = False
        else:
            date_format_string_is_valid = (
                "33" in formatted_date
                and "11" in formatted_date
                and "22" in formatted_date
            )

        if not date_format_string_is_valid:
            logging.warning(
                f'Client sent invalid date format string "{initial_message.date_format_string}". Using "%Y-%m-%d" instead.'
            )
            initial_message.date_format_string = "%Y-%m-%d"

        # Parse the timezone
        try:
            timezone = pytz.timezone(initial_message.timezone)
        except pytz.UnknownTimeZoneError:
            logging.warning(
                f'Client sent unknown timezone "{initial_message.timezone}". Using UTC instead.'
            )
            timezone = pytz.UTC

        base_url = url.with_path("").with_query("").with_fragment("")

        # Set the theme according to the user's preferences
        theme = self.app._theme
        if isinstance(theme, tuple):
            if initial_message.prefers_light_theme:
                theme = theme[0]
            else:
                theme = theme[1]

        # Prepare the initial URL. This will be exposed to the session as the
        # `active_page_url`, but overridden later once the page guards have been
        # run.
        initial_page_url = url

        # Create the session
        sess = session.Session(
            app_server_=self,
            send_message=send_message,
            receive_message=receive_message,
            websocket=websocket,
            client_ip=client_ip,
            client_port=client_port,
            http_headers=http_headers,
            base_url=base_url,
            active_page_url=initial_page_url,
            timezone=timezone,
            preferred_languages=preferred_languages,
            month_names_long=initial_message.month_names_long,
            day_names_long=initial_message.day_names_long,
            date_format_string=initial_message.date_format_string,
            first_day_of_week=first_day_of_week,
            decimal_separator=initial_message.decimal_separator,
            thousands_separator=initial_message.thousands_separator,
            window_width=initial_message.window_width,
            window_height=initial_message.window_height,
            theme_=theme,
        )

        # Deserialize the user settings
        await sess._load_user_settings(initial_message.user_settings)

        # Add any remaining attachments
        for attachment in self.app.default_attachments:
            if not isinstance(attachment, user_settings_module.UserSettings):
                sess.attach(attachment)

        # Trigger the `on_session_start` event.
        #
        # Since this event is often used for important initialization tasks like
        # adding attachments, actually wait for it to finish before continuing.
        #
        # However, also don't run it too early, since this function expects a
        # (mostly) functioning session.
        #
        # TODO: Figure out which values are still missing, and expose them,
        #       expose placeholders, or document that they aren't available.
        start_time = time.monotonic()
        await sess._call_event_handler(
            self.app._on_session_start,
            sess,
            refresh=False,
        )
        duration = time.monotonic() - start_time

        if duration > 5:
            warnings.warn(
                f"Session startup was delayed for {duration:.0f} seconds by"
                f" `on_session_start`. If you have long-running operations that"
                f" don't have to finish before the session starts, you should"
                f" execute them in a background task."
            )

        # Run any page guards for the initial page. Throws a `NavigationFailed`
        # if a page guard crashed.
        (
            active_page_instances,
            active_page_url_absolute,
        ) = routing.check_page_guards(sess, initial_page_url)

        # Is this a page, or a full URL to another site?
        try:
            utils.make_url_relative(
                sess._base_url,
                active_page_url_absolute,
            )

        # This is an external URL. Navigate to it
        except ValueError:

            async def history_worker() -> None:
                await sess._evaluate_javascript(
                    f"""
                    window.location.href = {json.dumps(str(active_page_url_absolute))};
                    """
                )

            sess.create_task(history_worker(), name="navigate to external URL")

            # TODO: End the session? Abort initialization?

        # Set the initial page URL. When connecting to the server, all relevant
        # page guards execute. These may change the URL of the page, so the
        # client needs to take care to update the browser's URL to match the
        # server's.
        if active_page_url_absolute != initial_page_url:

            async def update_url_worker():
                js_page_url = json.dumps(str(active_page_url_absolute))
                await sess._evaluate_javascript(
                    f"""
                    console.trace("Updating browser URL to match the one modified by guards:", {js_page_url});
                    window.history.replaceState(null, "", {js_page_url});
                    """
                )

            sess.create_task(
                update_url_worker(),
                name="Update browser URL to match the one modified by guards",
            )

        # Update the session's active page and instances
        sess._active_page_instances = tuple(active_page_instances)
        sess._active_page_url = active_page_url_absolute

        # Apply the CSS for the chosen theme
        await sess._apply_theme(theme)

        # Send the first `updateComponentStates` message
        await sess._refresh()

        # Start listening for incoming messages
        self._session_receive_tasks[sess] = asyncio.create_task(sess.serve())

        return sess
