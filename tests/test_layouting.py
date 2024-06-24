from collections.abc import Callable

import pytest

import rio.testing
from rio.components.flow_container import FlowContainer
from rio.components.linear_containers import Row
from rio.components.scroll_container import ScrollContainer
from rio.components.text import Text
from rio.data_models import ComponentLayout
from tests.utils.headless_client import HeadlessClient


async def verify_layout(build: Callable[[], rio.Component]) -> None:
    async with HeadlessClient(build) as test_client:
        layouter = await test_client.create_layouter()

        for component_id, layout_should in layouter._layouts_should.items():
            layout_is = layouter._layouts_are[component_id]

            differences = list[str]()
            for attribute in ComponentLayout.__annotations__:
                # Not all attributes are meant to be compared
                if attribute == "parent_id":
                    continue

                value_should = getattr(layout_should, attribute)
                value_is = getattr(layout_is, attribute)

                difference = abs(value_is - value_should)
                if difference > 0.2:
                    differences.append(
                        f"{attribute}: {value_is} != {value_should}"
                    )

            if differences:
                component = test_client.get_component_by_id(component_id)
                raise ValueError(
                    f"Layout of component {component} is incorrect:\n- "
                    + "\n- ".join(differences)
                )


def row_with_no_extra_width() -> Row:
    return rio.Row(
        rio.Text("hi", width=100),
        rio.Button("clicky", width=400),
    )


def row_with_extra_width_and_no_growers() -> Row:
    return rio.Row(
        rio.Text("hi", width=5),
        rio.Button("clicky", width=10),
        width=25,
    )


def row_with_extra_width_and_one_grower() -> Row:
    return rio.Row(
        rio.Text("hi", width=5),
        rio.Button("clicky", width="grow"),
        width=20,
    )


def scrolling_in_both_directions() -> ScrollContainer:
    return rio.ScrollContainer(
        rio.Text("hi", width=30, height=30),
        width=20,
        height=20,
        align_x=0.5,
        align_y=0.5,
    )


def scrolling_horizontally() -> ScrollContainer:
    return rio.ScrollContainer(
        rio.Text("hi", width=30, height=30),
        width=20,
        height=20,
        align_x=0.5,
        align_y=0.5,
        scroll_y="never",
    )


def scrolling_vertically() -> ScrollContainer:
    return rio.ScrollContainer(
        rio.Text("hi", width=30, height=30),
        width=20,
        height=20,
        align_x=0.5,
        align_y=0.5,
        scroll_x="never",
    )


def ellipsized_text() -> Text:
    return rio.Text(
        "My natural size should become 0",
        wrap="ellipsize",
        align_x=0,
    )


@pytest.mark.parametrize(
    "build",
    [
        row_with_no_extra_width,
        row_with_extra_width_and_no_growers,
        row_with_extra_width_and_one_grower,
        scrolling_in_both_directions,
        scrolling_horizontally,
        scrolling_vertically,
        ellipsized_text,
    ],
)
@pytest.mark.async_timeout(20)
async def test_layout(build: Callable[[], rio.Component]) -> None:
    await verify_layout(build)


@pytest.mark.parametrize(
    "justify",
    ["left", "right", "center", "justified", "grow"],
)
@pytest.mark.async_timeout(20)
async def test_flow_container_layout(justify: str) -> None:
    def build() -> FlowContainer:
        return rio.FlowContainer(
            rio.Text("foo", width=5),
            rio.Text("bar", width=10),
            rio.Text("qux", width=4),
            column_spacing=3,
            row_spacing=2,
            justify=justify,  # type: ignore
            width=20,
            align_x=0,
        )

    await verify_layout(build)
