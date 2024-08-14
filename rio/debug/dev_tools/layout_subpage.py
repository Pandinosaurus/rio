from __future__ import annotations

from dataclasses import KW_ONLY
from typing import *  # type: ignore

import rio
import rio.components.fundamental_component
import rio.debug.dev_tools.layout_display

from . import layout_explainer


class SizeControls(rio.Component):
    label: Literal["width", "height"]
    grow: bool
    min_value: float

    _: KW_ONLY

    on_grow_change: rio.EventHandler[bool] = None
    on_min_change: rio.EventHandler[float] = None

    async def _on_grow_change(
        self,
        event: rio.SwitchChangeEvent,
    ) -> None:
        self.grow = event.is_on
        await self.call_event_handler(self.on_grow_change, self.grow)

    async def _on_min_value_change(
        self,
        event: rio.NumberInputChangeEvent,
    ) -> None:
        self.min_value = event.value
        await self.call_event_handler(self.on_min_change, self.min_value)

    def build(self) -> rio.Component:
        axis_xy = "x" if self.label == "width" else "y"

        return rio.Grid(
            [
                rio.Switch(
                    is_on=self.grow,
                    on_change=lambda event: self._on_grow_change,
                ),
                rio.Text(
                    f"Grow {axis_xy.capitalize()}",
                    grow_x=True,
                ),
            ],
            rio.NumberInput(
                label=f"Min {self.label.capitalize()}",
                value=self.min_value,
                on_change=self._on_min_value_change,
            ),
            row_spacing=0.5,
            column_spacing=0.5,
        )


class AlignmentControls(rio.Component):
    label: str
    value: float | None

    _: KW_ONLY

    on_change: rio.EventHandler[float | None] = None

    async def _on_switch_change(self, event: rio.SwitchChangeEvent) -> None:
        if event.is_on:
            self.value = 0.5
        else:
            self.value = None

        await self.call_event_handler(self.on_change, self.value)

    async def _on_slider_change(self, event: rio.SliderChangeEvent) -> None:
        self.value = event.value
        await self.call_event_handler(self.on_change, self.value)

    def build(self) -> rio.Component:
        # If enabled, add a slider to control the alignment value
        if self.value is None:
            slider = None
        else:
            slider = rio.Slider(
                value=self.value,
                minimum=0,
                maximum=1,
                show_values=True,
                on_change=self._on_slider_change,
                margin_top=1,
                margin_bottom=0.5,
            )

        # Allow enabling / disabling alignment
        return rio.Grid(
            [
                rio.Switch(
                    is_on=self.value is not None,
                    on_change=self._on_switch_change,
                ),
                rio.Text(
                    self.label,
                    align_x=0,
                    grow_x=True,
                ),
            ],
            rio.Switcher(slider),
            row_spacing=0.5,
            column_spacing=0.5,
        )


class HelpAnchor(rio.Component):
    content: str

    def build(self) -> rio.Component:
        return rio.Tooltip(
            # The rectangle increases the area the user can hover over
            anchor=rio.Rectangle(
                content=rio.Row(
                    rio.Icon("material/help", fill="secondary"),
                    rio.Text(
                        "Help",
                        style=rio.TextStyle(
                            fill=self.session.theme.secondary_color
                        ),
                    ),
                    spacing=0.5,
                    margin_y=0.5,
                    align_x=0,
                ),
                fill=rio.Color.TRANSPARENT,
            ),
            tip=rio.Markdown(
                self.content,
                min_width=25,
            ),
            position="left",
            gap=2,
            align_x=0,
        )


class ActionAnchor(rio.Component):
    icon: str
    partial_name: str
    actions: list[str]

    def build(self) -> rio.Component:
        # Prepare the anchor
        if len(self.actions) == 0:
            color = self.session.theme.disabled_color
        else:
            color = self.session.theme.secondary_color

        anchor = rio.Row(
            rio.Icon(self.icon, fill=color),
            rio.Text(
                f"How-to {self.partial_name}",
                style=rio.TextStyle(fill=color),
            ),
            spacing=0.3,
            align_x=0.5,
            margin=0.5,
        )

        # If there aren't any options there is no need to go any further
        if not self.actions:
            return anchor

        # Prepare the markdown content
        if len(self.actions) == 1:
            markdown_source = self.actions[0]
        else:
            markdown_source = "- " + "\n- ".join(self.actions)

        # Build the UI
        return rio.Tooltip(
            anchor=anchor,
            tip=rio.Markdown(
                markdown_source,
                min_width=25,
            ),
            position="left",
            gap=-2,
        )


class LayoutSubpage(rio.Component):
    component_id: int

    _: KW_ONLY

    _layout_explainer: layout_explainer.LayoutExplainer | None = None
    _explanation_is_expanded: bool = True

    def get_target_component(self) -> rio.Component:
        return self.session._weak_components_by_id[self.component_id]

    @rio.event.on_populate
    async def _update_explanations(self) -> None:
        # Get human-readable layout explanations
        target = self.get_target_component()

        try:
            self._layout_explainer = (
                await layout_explainer.LayoutExplainer.create_new(
                    self.session,
                    target,
                )
            )
        # This is raised if the component cannot be found client-side, e.g. due
        # to network lag
        except KeyError:
            self._layout_explainer = None

    async def _update_target_attribute(self, name: str, value: Any) -> None:
        """
        Updates an attribute of the target component.

        This is more complicated than just setting the attribute, because Rio
        must be notified of the change in order to update the display.
        """
        target = self.get_target_component()

        # Assign the new value to the Python instance
        setattr(target, name, value)

        # Components will automatically mark themselves as dirty, but won't
        # trigger a resync. Do that now.
        await self.session._refresh()

        # Update the explanations
        await self._update_explanations()

    def _build_explanations(self) -> rio.Component:
        if self._layout_explainer is None:
            return rio.Text(
                "No explanations available",
                style="dim",
                justify="left",
                margin_y=0.5,
            )

        content = rio.Column(
            spacing=0.5,
            # Push away the silly rounded corner created by the revealer. It
            # looks silly when cutting off warnings.
            margin_bottom=0.5,
        )

        # Explain the width
        content.add(
            rio.Markdown(
                f"**Width**: {self._layout_explainer.width_explanation}",
            )
        )

        content.add(
            rio.Row(
                ActionAnchor(
                    "close-fullscreen",
                    "Shrink Width",
                    self._layout_explainer.decrease_width,
                ),
                ActionAnchor(
                    "open-in-full",
                    "Grow Width",
                    self._layout_explainer.increase_width,
                ),
            )
        )

        # Explain the height
        content.add(
            rio.Markdown(
                f"**Height**: {self._layout_explainer.height_explanation}",
            )
        )

        content.add(
            rio.Row(
                ActionAnchor(
                    "close-fullscreen",
                    "Shrink Height",
                    self._layout_explainer.decrease_height,
                ),
                ActionAnchor(
                    "open-in-full",
                    "Grow Height",
                    self._layout_explainer.increase_height,
                ),
            )
        )

        # Add warnings
        for warning in self._layout_explainer.warnings:
            content.add(
                rio.Row(
                    rio.Rectangle(
                        fill=self.session.theme.warning_color,
                        min_width=0.3,
                    ),
                    rio.Markdown(
                        warning,
                        grow_x=True,
                    ),
                    spacing=0.5,
                    margin_top=0.5,
                )
            )

        return content

    def _build_margin_controls(self) -> rio.Component:
        result = rio.Grid(
            row_spacing=0.3,
            column_spacing=0.3,
        )

        # Add a visual stand-in for the target component
        target = self.get_target_component()
        result.add(
            rio.Card(
                content=rio.Text(
                    type(target).__name__,
                    justify="center",
                ),
                color="secondary",
                corner_radius=self.session.theme.corner_radius_small,
            ),
            1,
            1,
        )

        # And controls for the margin
        result.add(
            rio.NumberInput(
                label="Left",
                value=target._effective_margin_left,
                minimum=0,
                on_change=lambda event: self._update_target_attribute(
                    "margin_left", event.value
                ),
            ),
            1,
            0,
        )

        result.add(
            rio.NumberInput(
                label="Top",
                value=target._effective_margin_top,
                minimum=0,
                on_change=lambda event: self._update_target_attribute(
                    "margin_top", event.value
                ),
            ),
            0,
            1,
        )

        result.add(
            rio.NumberInput(
                label="Right",
                value=target._effective_margin_right,
                minimum=0,
                on_change=lambda event: self._update_target_attribute(
                    "margin_right", event.value
                ),
            ),
            1,
            2,
        )

        result.add(
            rio.NumberInput(
                label="Bottom",
                value=target._effective_margin_bottom,
                minimum=0,
                on_change=lambda event: self._update_target_attribute(
                    "margin_bottom", event.value
                ),
            ),
            2,
            1,
        )

        result.add(
            HelpAnchor(
                """
Margin adds empty space around the component. You can either specify each side
separately, or use one of the shortcuts `margin`, `margin_x`, `margin_y`.
                """,
            ),
            3,
            0,
            width=3,
        )

        return result

    def _build_size_controls(self) -> rio.Component:
        target_component = self.get_target_component()

        return rio.Column(
            SizeControls(
                label="width",
                grow=target_component.grow_x,
                min_value=target_component.min_width,
                on_grow_change=lambda value: self._update_target_attribute(
                    "grow_x", value
                ),
                on_min_change=lambda value: self._update_target_attribute(
                    "min_width", value
                ),
            ),
            SizeControls(
                label="height",
                grow=target_component.grow_y,
                min_value=target_component.min_height,
                on_grow_change=lambda value: self._update_target_attribute(
                    "grow_y", value
                ),
                on_min_change=lambda value: self._update_target_attribute(
                    "min_height", value
                ),
            ),
            HelpAnchor(
                """
`"natural"` components take up as little space as necessary.

Components with `"grow"` take priority when too much space is available. This is
only relevant in components that have multiple children, such as `Row` and
`Column`.

Components with custom size take up at least the specified amount of space, but
never less than their natural size.

Above all, **components always take up all superfluous space from their
parent**. If you don't want for that to happen, set an alignment.
                """,
            ),
            spacing=0.5,
        )

    def _build_alignment_controls(self) -> rio.Component:
        target = self.get_target_component()

        return rio.Column(
            AlignmentControls(
                label="Align X",
                value=target.align_x,
                on_change=lambda value: self._update_target_attribute(
                    "align_x", value
                ),
            ),
            AlignmentControls(
                label="Align Y",
                value=target.align_y,
                on_change=lambda value: self._update_target_attribute(
                    "align_y", value
                ),
            ),
            HelpAnchor(
                """
Unaligned components take up the full space assigned by their parent. Aligned
components only take up as little space as necessary to display their content.

Components with an alignment of `0` are left/top-aligned, `0.5` are centered,
and `1` are right/bottom-aligned.
                    """
            ),
            margin_top=0.3,
            spacing=0.5,
        )

    def build(self) -> rio.Component:
        return rio.Column(
            rio.debug.dev_tools.layout_display.LayoutDisplay(
                component_id=self.bind().component_id,
                max_requested_height=20,
                min_height=20,
                on_component_change=lambda _: self._update_explanations(),
                on_layout_change=self._update_explanations,
            ),
            rio.Revealer(
                header="Explanation",
                content=self._build_explanations(),
                header_style="heading3",
                is_open=self.bind()._explanation_is_expanded,
            ),
            rio.Revealer(
                header="Margin",
                content=self._build_margin_controls(),
                header_style="heading3",
            ),
            rio.Revealer(
                header="Size",
                content=self._build_size_controls(),
                header_style="heading3",
            ),
            rio.Revealer(
                header="Alignment",
                content=self._build_alignment_controls(),
                header_style="heading3",
            ),
            rio.Spacer(),
            rio.Link(
                rio.Row(
                    rio.Icon("material/library_books", fill="secondary"),
                    rio.Text(
                        "Layouting Quickstart",
                        style=rio.TextStyle(
                            fill=self.session.theme.secondary_color
                        ),
                    ),
                    spacing=0.5,
                    margin_y=1,
                    align_x=0,
                ),
                target_url="https://rio.dev/docs/howto/layout-guide?s=w1q",
                open_in_new_tab=True,
                align_x=0,
            ),
            spacing=0.5,
        )
