import pytest
import tl


def test_outer_html_and_inner_html():
    dom = tl.parse("<div>abc <p id='text'>hello <span>world</span></p> def</div>")
    node = dom.get_element_by_id("text")
    assert node.outer_html() == '<p id="text">hello <span>world</span></p>'
    assert node.inner_html() == "hello <span>world</span>"
    assert dom.outer_html() == '<div>abc <p id="text">hello <span>world</span></p> def</div>'


def test_get_element_by_id_and_class_name():
    dom = tl.parse("<div></div><p class='a b' id='t'>hey</p><p></p>")

    node = dom.get_element_by_id("t")
    assert node.inner_text() == "hey"

    matches = dom.get_elements_by_class_name("a")
    assert [el.inner_text() for el in matches] == ["hey"]
    assert node.class_list() == ["a", "b"]
    assert node.has_class("a") is True
    assert node.has_class("missing") is False


def test_attributes_helpers():
    dom = tl.parse("<p id='t' class='a b' data-x='1'></p>")
    node = dom.get_element_by_id("t")

    attrs = node.attributes()
    assert attrs["id"] == "t"
    assert attrs["class"] == "a b"
    assert attrs["data-x"] == "1"
    assert node.class_name() == "a b"
    assert node.id() == "t"


def test_query_selector_and_node_type():
    dom = tl.parse("<!-- comment --><div class='x'><span class='y'>hi</span></div> tail")
    root_types = [child.node_type() for child in dom.children()]
    assert root_types == ["comment", "element", "text"]

    div = dom.query_selector("div.x")[0]
    spans = div.query_selector("span.y")
    assert [el.inner_text() for el in spans] == ["hi"]

    with pytest.raises(ValueError):
        dom.query_selector("div:???")


def test_version_detected():
    dom = tl.parse("<!DOCTYPE html><html><body><p>ok</p></body></html>")
    assert dom.version() == "html5"
